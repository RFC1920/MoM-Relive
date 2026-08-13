import json
import os
import signal
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import backend
import client_launcher
import linux_client
import linux_configure
import mom_revival
import momlib
import native_server
import redirect_urls
import server_manager

AWS_URL = "https://7pxwu4beee.execute-api.eu-west-1.amazonaws.com/Prod/"
AWS_AUTH_URL = "https://l32aayf7lh.execute-api.eu-central-1.amazonaws.com/Prod/"


def fake_exe(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"MZ"
        + AWS_URL.encode("ascii")
        + b"\0tail"
        + AWS_URL.encode("utf-16le")
        + b"\0\0end"
    )


def fake_linux_server(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x7fELF"
        + AWS_URL.encode("ascii")
        + b"\0tail"
        + AWS_AUTH_URL.encode("utf-32le")
        + b"\0\0\0\0end"
    )
    path.chmod(0o755)


class ClientLauncherTests(unittest.TestCase):
    def test_direct_launch_provides_the_official_steam_app_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / client_launcher.CLIENT_EXE_REL
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"MZ")
            process = mock.MagicMock(pid=1234)
            with (
                mock.patch("client_launcher._game_root", return_value=root),
                mock.patch("client_launcher._settings", return_value={}),
                mock.patch("client_launcher._restore_system_dll_search"),
                mock.patch("client_launcher.subprocess.Popen", return_value=process) as popen,
                mock.patch("client_launcher.os.cpu_count", return_value=4),
                mock.patch("client_launcher._log"),
            ):
                self.assertEqual(client_launcher.main(), 0)

            env = popen.call_args.kwargs["env"]
            self.assertEqual(env["SteamAppId"], "644290")
            self.assertEqual(env["SteamGameId"], "644290")

    @unittest.skipUnless(client_launcher.os.name == "nt", "Windows-only behavior")
    def test_external_game_uses_the_system_dll_search_path(self):
        kernel32 = mock.MagicMock()
        kernel32.SetDllDirectoryW.return_value = 1
        with mock.patch("client_launcher.ctypes.WinDLL", return_value=kernel32):
            client_launcher._restore_system_dll_search()
        kernel32.SetDllDirectoryW.assert_called_once_with(None)

    @unittest.skipUnless(client_launcher.os.name == "nt", "Windows-only behavior")
    def test_dll_search_restore_failure_is_not_ignored(self):
        kernel32 = mock.MagicMock()
        kernel32.SetDllDirectoryW.return_value = 0
        with (
            mock.patch("client_launcher.ctypes.WinDLL", return_value=kernel32),
            mock.patch("client_launcher.ctypes.get_last_error", return_value=5),
            self.assertRaisesRegex(OSError, "DLL search path"),
        ):
            client_launcher._restore_system_dll_search()


class ClientApplicationTests(unittest.TestCase):
    def tearDown(self):
        mom_revival._INSTANCE_MUTEX = None

    def test_single_instance_mutex_is_kept_until_release(self):
        kernel32 = mock.MagicMock()
        kernel32.CreateMutexW.return_value = 4321
        with (
            mock.patch("mom_revival.os.name", "nt"),
            mock.patch("mom_revival.ctypes.WinDLL", return_value=kernel32),
            mock.patch("mom_revival.ctypes.get_last_error", return_value=0),
        ):
            self.assertTrue(mom_revival.acquire_single_instance())
            mom_revival.release_single_instance()

        kernel32.CreateMutexW.assert_called_once_with(
            None, False, mom_revival._INSTANCE_MUTEX_NAME
        )
        kernel32.CloseHandle.assert_called_once_with(4321)

    def test_second_client_instance_is_rejected(self):
        kernel32 = mock.MagicMock()
        kernel32.CreateMutexW.return_value = 4321
        with (
            mock.patch("mom_revival.os.name", "nt"),
            mock.patch("mom_revival.ctypes.WinDLL", return_value=kernel32),
            mock.patch("mom_revival.ctypes.get_last_error", return_value=183),
        ):
            self.assertFalse(mom_revival.acquire_single_instance())

        kernel32.CloseHandle.assert_called_once_with(4321)
        self.assertIsNone(mom_revival._INSTANCE_MUTEX)


class BinaryPatchTests(unittest.TestCase):
    def test_patch_keeps_size_and_restore_is_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "game.exe"
            fake_exe(exe)
            original = exe.read_bytes()
            replaced = redirect_urls.patch(exe, "http://127.0.0.1:8080/r/abcd/1/")
            self.assertEqual(replaced, 2)
            self.assertEqual(len(exe.read_bytes()), len(original))
            self.assertIn(b"http://127.0.0.1:8080/r/abcd/1/", exe.read_bytes())
            self.assertEqual(
                redirect_urls.verify(exe, "http://127.0.0.1:8080/r/abcd/1/"), 2
            )
            self.assertTrue(redirect_urls.restore(exe))
            self.assertEqual(exe.read_bytes(), original)

    def test_binary_verification_rejects_an_old_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "game.exe"
            fake_exe(exe)
            redirect_urls.patch(exe, "http://127.0.0.1:8080/r/abcd/1/")

            with self.assertRaisesRegex(redirect_urls.PatchError, "not redirected"):
                redirect_urls.verify(exe, "http://192.0.2.1:8080/r/abcd/1/")

    def test_locked_game_binary_has_an_actionable_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "MemoriesOfMars.exe"
            fake_exe(exe)
            exe.with_suffix(".exe.orig").write_bytes(exe.read_bytes())
            real_replace = os.replace

            def replace_unless_game(source, destination):
                if Path(destination) == exe:
                    raise PermissionError(5, "Access is denied", str(exe))
                return real_replace(source, destination)

            with (
                mock.patch(
                    "redirect_urls.os.replace", side_effect=replace_unless_game
                ),
                self.assertRaisesRegex(
                    redirect_urls.PatchError, "Close Memories of Mars completely"
                ),
            ):
                redirect_urls.patch(
                    exe, "http://127.0.0.1:8080/r/abcd/12345/"
                )

    def test_rejects_url_that_does_not_fit(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "game.exe"
            fake_exe(exe)
            with self.assertRaises(redirect_urls.PatchError):
                redirect_urls.patch(exe, "http://" + "x" * 70 + "/")
            self.assertEqual(
                exe.read_bytes(), exe.with_suffix(".exe.orig").read_bytes()
            )

    def test_steam_update_refreshes_original_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "game.exe"
            fake_exe(exe)
            redirect_urls.patch(exe, "http://127.0.0.1:8080/r/abcd/1/")
            updated = b"new-version-" + AWS_URL.encode("ascii") + b"\0"
            exe.write_bytes(updated)
            redirect_urls.patch(exe, "http://127.0.0.1:8080/r/abcd/1/")
            redirect_urls.restore(exe)
            self.assertEqual(exe.read_bytes(), updated)

    @unittest.skipUnless(os.name == "posix", "POSIX-only executable modes")
    def test_linux_utf32_urls_and_executable_mode_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "MemoriesOfMarsServer"
            fake_linux_server(exe)
            original = exe.read_bytes()
            url = "http://127.0.0.1:8080/r/abcd/s/"

            replaced = redirect_urls.patch(exe, url)

            self.assertEqual(replaced, 2)
            self.assertIn(url.encode("ascii"), exe.read_bytes())
            self.assertIn(url.encode("utf-32le"), exe.read_bytes())
            self.assertEqual(exe.stat().st_mode & 0o777, 0o755)
            self.assertTrue(redirect_urls.restore(exe))
            self.assertEqual(exe.read_bytes(), original)
            self.assertEqual(exe.stat().st_mode & 0o777, 0o755)


class ConfigTests(unittest.TestCase):
    def test_project_document_rejects_arbitrary_paths(self):
        with self.assertRaisesRegex(momlib.ConfigError, "Unsupported"):
            momlib.project_document("../secret.txt")

    def test_existing_world_with_more_player_data_is_preferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = Path(tmp) / "server"
            sparse = server / "Game/Saved/DB/Serversparse/Version_1.1/PlayerData/1"
            complete = server / "Game/Saved/DB/Servercomplete/Version_1.1/PlayerData/1"
            sparse.mkdir(parents=True)
            complete.mkdir(parents=True)
            (sparse / "Stats.json").write_text("{}", encoding="utf-8")
            for name in ("Stats.json", "Inventory.json", "Flops.json"):
                (complete / name).write_text("{}", encoding="utf-8")

            worlds = momlib.discover_server_worlds(server)

            self.assertEqual(worlds[0]["server_id"], "complete")
            self.assertEqual(worlds[0]["players"], 1)
            self.assertEqual(worlds[0]["player_files"], 3)

    def test_ini_apply_and_restore_preserve_unrelated_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini = Path(tmp) / "Engine.ini"
            ini.write_text(
                "[Core.System]\nPaths=keep\n\n[OnlineSubsystemLimbic]\nOther=keep\n",
                encoding="utf-8",
            )
            momlib.set_limbic_url(ini, "http://127.0.0.1:8080/r/abcd/1/")
            text = ini.read_text(encoding="utf-8")
            self.assertEqual(text.count("BaseURL="), 2)
            momlib.remove_ini_key(ini, momlib.LIMBIC_SECTION, "BaseURL")
            text = ini.read_text(encoding="utf-8")
            self.assertIn("Paths=keep", text)
            self.assertIn("Other=keep", text)
            self.assertNotIn("BaseURL", text)

    def test_client_ini_verification_requires_the_exact_url_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini = Path(tmp) / "Engine.ini"
            expected = "http://203.0.113.20:18080/r/deadbeef/p/"
            momlib.set_limbic_url(ini, expected)

            result = momlib.verify_client_ini(ini, expected)

            self.assertEqual(result["base_urls"], 2)
            with self.assertRaisesRegex(momlib.ConfigError, "not the configured"):
                momlib.verify_client_ini(
                    ini, "http://203.0.113.21:18080/r/deadbeef/p/"
                )

    def test_repair_client_ini_uses_the_selected_file_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selected = root / "OtherProfile/Engine.ini"
            default = root / "Default/Engine.ini"
            default.parent.mkdir(parents=True)
            default.write_text("keep-default\n", encoding="utf-8")

            result = momlib.repair_client_ini(
                "203.0.113.20", 18080, "deadbeef", selected
            )

            self.assertEqual(result["ini"], str(selected.resolve()))
            self.assertEqual(
                momlib.client_ini_urls(selected),
                [result["url"], result["url"]],
            )
            self.assertEqual(default.read_text(encoding="utf-8"), "keep-default\n")

    def test_close_windows_client_processes_reports_closed_or_absent(self):
        closed = mock.MagicMock(returncode=0, stdout="", stderr="")
        absent = mock.MagicMock(returncode=128, stdout="", stderr="")
        with (
            mock.patch("momlib.os.name", "nt"),
            mock.patch("momlib.subprocess.run", side_effect=[closed, absent]) as run,
        ):
            self.assertTrue(momlib.close_windows_client_processes())
            self.assertFalse(momlib.close_windows_client_processes())

        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            run.call_args_list[0].args[0],
            ["taskkill.exe", "/F", "/T", "/IM", "MemoriesOfMars.exe"],
        )

    def test_close_windows_client_processes_explains_taskkill_failure(self):
        failed = mock.MagicMock(returncode=5, stdout="", stderr="access denied")
        with (
            mock.patch("momlib.os.name", "nt"),
            mock.patch("momlib.subprocess.run", return_value=failed),
            self.assertRaisesRegex(OSError, "access denied"),
        ):
            momlib.close_windows_client_processes()

    def test_client_repair_removes_stale_urls_from_duplicate_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini = Path(tmp) / "Engine.ini"
            ini.write_text(
                "[OnlineSubsystemLimbic]\n"
                'BaseURL="http://old.invalid/r/old/p/"\n'
                "Keep=first\n\n"
                "[Core.System]\nPaths=keep\n\n"
                "[onlinesubsystemlimbic]\n"
                'BaseURL="http://also-old.invalid/r/old/p/"\n'
                "Keep=second\n",
                encoding="utf-8",
            )
            expected = "http://203.0.113.20:18080/r/deadbeef/p/"

            momlib.set_limbic_url(ini, expected)

            self.assertEqual(momlib.client_ini_urls(ini), [expected, expected])
            text = ini.read_text(encoding="utf-8")
            self.assertIn("Keep=first", text)
            self.assertIn("Keep=second", text)
            self.assertIn("Paths=keep", text)

    def test_client_and_server_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = root / "client"
            server = root / "server"
            fake_exe(client / momlib.CLIENT_EXE_REL)
            fake_exe(server / momlib.SERVER_EXE_REL)
            (server / momlib.SERVER_CFG_REL).write_text(
                json.dumps({"ServerName": "old", "EnableEAC": True}), encoding="utf-8"
            )
            ini = root / "client.ini"

            result = momlib.apply_client(client, "127.0.0.1", 8080, "abcd", ini)
            self.assertIn("/abcd/p/", result["url"])
            self.assertFalse(
                (server / momlib.SERVER_EXE_REL).with_suffix(".exe.orig").exists()
            )

            result = momlib.apply_server(
                server, "127.0.0.1", 8080, "abcd", server_name="new", max_players=4
            )
            self.assertIn("/abcd/s/", result["url"])
            cfg = json.loads(
                (server / momlib.SERVER_CFG_REL).read_text(encoding="utf-8")
            )
            self.assertEqual(cfg["ServerName"], "new")
            self.assertEqual(cfg["MaxPlayers"], 4)
            self.assertFalse(cfg["EnableEAC"])
            momlib.restore_server(server)
            game_ini = (server / momlib.SERVER_GAME_REL).read_text(encoding="utf-8")
            self.assertNotIn("bNeverSpawnInCloningFacility", game_ini)
            cfg = json.loads(
                (server / momlib.SERVER_CFG_REL).read_text(encoding="utf-8")
            )
            self.assertTrue(cfg["EnableEAC"])

    def test_compatibility_only_preserves_native_server_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = Path(tmp) / "server"
            fake_exe(server / momlib.SERVER_EXE_REL)
            config = server / momlib.SERVER_CFG_REL
            config.write_text(
                json.dumps(
                    {
                        "ServerName": "Configured natively",
                        "ServerPassword": "keep-me",
                        "ServerID": "native-world",
                        "MaxPlayers": 23,
                        "EnableEAC": True,
                    }
                ),
                encoding="utf-8",
            )

            momlib.apply_server_compatibility(
                server, "127.0.0.1", 8080, "abcd"
            )

            updated = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(updated["ServerName"], "Configured natively")
            self.assertEqual(updated["ServerPassword"], "keep-me")
            self.assertEqual(updated["ServerID"], "native-world")
            self.assertEqual(updated["MaxPlayers"], 23)
            self.assertFalse(updated["EnableEAC"])

    def test_linux_server_uses_linuxserver_config_and_native_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = Path(tmp) / "server"
            fake_linux_server(server / momlib.LINUX_SERVER_EXE_REL)
            config = server / momlib.SERVER_CFG_REL
            config.write_text(
                json.dumps({"ServerName": "Linux", "EnableEAC": True}),
                encoding="utf-8",
            )

            result = momlib.apply_server_compatibility(
                server, "127.0.0.1", 8080, "abcd"
            )
            command, cwd, layout = momlib.server_launch_spec(server, ["-Port=7778"])

            self.assertEqual(result["platform"], "linux")
            self.assertTrue((server / momlib.LINUX_SERVER_ENGINE_REL).is_file())
            self.assertTrue((server / momlib.LINUX_SERVER_GAME_REL).is_file())
            self.assertFalse((server / "Game/Saved/Config/Linux/Game.ini").exists())
            self.assertEqual(layout.platform, "linux")
            self.assertEqual(command[1:], ["Game", "-log", "-Port=7778"])
            self.assertEqual(cwd, server.resolve())

    def test_server_openssl_compatibility_is_enabled_by_default(self):
        env = momlib.server_environment({}, {"KEEP": "yes"})

        self.assertEqual(env["OPENSSL_ia32cap"], ":~0x20000000")
        self.assertEqual(env["KEEP"], "yes")

    def test_server_openssl_compatibility_can_be_disabled(self):
        env = momlib.server_environment(
            {"server_openssl_compat": False},
            {"KEEP": "yes", "OPENSSL_ia32cap": "inherited-value"},
        )

        self.assertNotIn("OPENSSL_ia32cap", env)

    def test_client_launcher_replaces_eac_and_restores_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_exe(root / momlib.CLIENT_EXE_REL)
            official = root / momlib.CLIENT_LAUNCHER_REL
            official.write_bytes(b"official-eac-launcher")
            revival = root / "MoMClientLauncher.exe"
            revival.write_bytes(b"revival-launcher-v1")
            ini = root / "Engine.ini"

            result = momlib.apply_client(
                root,
                "127.0.0.1",
                8080,
                "abcd",
                ini,
                launcher_source=revival,
            )
            self.assertEqual(official.read_bytes(), revival.read_bytes())
            self.assertTrue(result["launcher"])
            self.assertTrue(momlib.client_launcher_is_installed(root))

            restored = momlib.restore_client(root, ini)
            self.assertTrue(restored["launcher_restored"])
            self.assertEqual(official.read_bytes(), b"official-eac-launcher")
            self.assertFalse(momlib.client_launcher_is_installed(root))

    def test_client_preparation_verifies_launcher_and_engine_ini(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_exe(root / momlib.CLIENT_EXE_REL)
            target = root / momlib.CLIENT_LAUNCHER_REL
            target.write_bytes(b"official")
            launcher = root / "MoMClientLauncher.exe"
            launcher.write_bytes(b"relive")
            ini = root / "Engine.ini"
            momlib.install_client_launcher(root, launcher)
            expected = "http://203.0.113.20:18080/r/deadbeef/p/"
            momlib.set_limbic_url(ini, expected)
            redirect_urls.patch(root / momlib.CLIENT_EXE_REL, expected)

            result = momlib.verify_client_preparation(
                root, "203.0.113.20", 18080, "deadbeef", ini
            )

            self.assertEqual(result["url"], expected)

    def test_client_launcher_refresh_preserves_latest_steam_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_exe(root / momlib.CLIENT_EXE_REL)
            target = root / momlib.CLIENT_LAUNCHER_REL
            target.write_bytes(b"official-v1")
            launcher = root / "MoMClientLauncher.exe"
            launcher.write_bytes(b"revival-v1")
            momlib.install_client_launcher(root, launcher)

            # Actualizar Revival no debe convertir el lanzador Revival anterior
            # en la copia supuestamente oficial.
            launcher.write_bytes(b"revival-v2")
            momlib.install_client_launcher(root, launcher)
            self.assertTrue(momlib.client_launcher_is_installed(root))
            momlib.restore_client_launcher(root)
            self.assertEqual(target.read_bytes(), b"official-v1")

            # Si Steam actualiza el fichero, esa versión sí pasa a ser la nueva
            # base restaurable antes de volver a aplicar Revival.
            target.write_bytes(b"official-v2")
            self.assertFalse(momlib.client_launcher_is_installed(root))
            momlib.install_client_launcher(root, launcher)
            momlib.restore_client_launcher(root)
            self.assertEqual(target.read_bytes(), b"official-v2")

    def test_client_always_uses_game_identity_passthrough(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_exe(root / momlib.CLIENT_EXE_REL)
            result = momlib.apply_client(
                root, "127.0.0.1", 8080, "abcd", root / "Engine.ini"
            )
            self.assertIn("/abcd/p/", result["url"])

    def test_obsolete_settings_are_discarded_during_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(
                json.dumps({"access_key": "efgh", "obsolete_setting": "12345"}),
                encoding="utf-8",
            )

            result = momlib.load_settings(config)

            self.assertEqual(result["access_key"], "efgh")
            self.assertNotIn("obsolete_setting", result)

    def test_reapplying_an_identical_client_does_not_replace_the_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ini = root / "Engine.ini"
            fake_exe(root / momlib.CLIENT_EXE_REL)
            momlib.apply_client(root, "127.0.0.1", 8080, "abcd", ini)

            with mock.patch("momlib.redirect_urls.patch") as patch_binary:
                result = momlib.apply_client(
                    root, "127.0.0.1", 8080, "abcd", ini
                )

            patch_binary.assert_not_called()
            self.assertEqual(result["binary_urls"], 0)
            self.assertEqual(result["binary_verified"], 2)

    def test_public_ip_detection(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"203.0.113.20\n"
        with mock.patch("momlib.urllib.request.urlopen", return_value=response):
            self.assertEqual(momlib.detect_public_ip(), "203.0.113.20")

    def test_update_check_detects_a_new_official_release(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "tag_name": "v1.2.0",
                "html_url": "https://github.com/drbermejor/MoM-Relive/releases/tag/v1.2.0",
            }
        ).encode("utf-8")
        with mock.patch("momlib.urllib.request.urlopen", return_value=response) as open_url:
            result = momlib.check_latest_release("1.1.9")

        self.assertTrue(result["available"])
        self.assertEqual(result["latest"], "1.2.0")
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, momlib.LATEST_RELEASE_API)
        self.assertEqual(request.get_header("User-agent"), "MoM-Relive/1.1.9")

    def test_update_check_rejects_a_nonofficial_release_url(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "tag_name": "v9.0.0",
                "html_url": "https://github.com/drbermejor/MoM-Relive.evil/releases/tag/v9.0.0",
            }
        ).encode("utf-8")
        with (
            mock.patch("momlib.urllib.request.urlopen", return_value=response),
            self.assertRaisesRegex(momlib.ConfigError, "invalid latest release"),
        ):
            momlib.check_latest_release("0.8.3")

    def test_url_limit_is_explained(self):
        with self.assertRaisesRegex(momlib.ConfigError, "maximo 60"):
            momlib.backend_url(
                "a-very-long-backend-name.example.invalid",
                8080,
                "longaccesskey123",
                "76561198000000001",
            )

    def test_ipv6_url_uses_brackets(self):
        self.assertEqual(
            momlib.backend_url("::1", 8080, "abcd", "1"),
            "http://[::1]:8080/r/abcd/1/",
        )


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        data = Path(self.tmp.name)
        backend.STATE_FILE = data / "state.json"
        backend.TRACE_LOG = data / "requests.log"
        backend.UNKNOWN_LOG = data / "unknown.log"
        backend.STATE = backend._empty_state()
        backend.ACCESS_KEY = "abcd"
        backend.ADVERTISE_HOST = ""
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), backend.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, path, body=None, method=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status, json.load(response)

    def test_health_and_key_enforcement(self):
        status, body = self.request("/health")
        self.assertEqual((status, body["result"]), (200, "ok"))
        with self.assertRaises(urllib.error.HTTPError) as hit:
            self.request("/Login", {"steamaccid": "999"}, "POST")
        self.assertEqual(hit.exception.code, 403)
        hit.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as hit:
            self.request("/r/wrong/123/Login", {"steamaccid": "999"}, "POST")
        self.assertEqual(hit.exception.code, 403)
        hit.exception.close()

    def test_unsupported_identity_route_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as hit:
            self.request("/r/abcd/12345/Login", {"steamaccid": "999"}, "POST")
        self.assertEqual(hit.exception.code, 403)
        hit.exception.close()

    def test_passthrough_preserves_game_identity(self):
        _, login = self.request("/r/abcd/p/Login", {"steamaccid": "999"}, "POST")
        self.assertEqual(login["accid"], "999")
        _, patterns = self.request("/r/abcd/p/GetUnlockedPatterns/999")
        self.assertEqual(patterns["result"]["accid"], "999")

    def test_empty_pattern_list_uses_parser_compatible_sentinel(self):
        _, patterns = self.request("/r/abcd/p/GetUnlockedPatterns/empty-account")
        self.assertEqual(patterns["result"]["pids"], [-1])

    def test_public_host_overrides_private_server_address(self):
        backend.ADVERTISE_HOST = "game.example.net"
        _, created = self.request(
            "/r/abcd/s/CreateSession",
            {"IpAddress": "192.168.50.122", "Port": 7777},
            "POST",
        )
        self.assertEqual(created["IpAddress"], "game.example.net")
        _, updated = self.request(
            "/r/abcd/s/UpdateSession",
            {"SessionId": created["SessionId"], "IpAddress": "10.0.0.2"},
            "PATCH",
        )
        self.assertEqual(updated["IpAddress"], "game.example.net")
        local = backend.all_sessions(
            mock.MagicMock(query={}, remote_addr="127.0.0.1")
        )
        remote = backend.all_sessions(
            mock.MagicMock(query={}, remote_addr="8.8.8.8")
        )
        self.assertEqual(local["Sessions"][0]["IpAddress"], "10.0.0.2")
        self.assertEqual(remote["Sessions"][0]["IpAddress"], "game.example.net")

    def test_remote_backend_detects_the_game_servers_public_address(self):
        created = backend.create_session(
            {"IpAddress": "192.168.1.76", "Port": 7777}, "1.1.1.1"
        )
        self.assertEqual(created["IpAddress"], "1.1.1.1")
        stored = backend.STATE["sessions"][created["SessionId"]]
        self.assertEqual(stored["_private_ip"], "192.168.1.76")
        self.assertEqual(stored["_advertise_mode"], "detected")

        backend_local = backend.all_sessions(
            mock.MagicMock(query={}, remote_addr="127.0.0.1")
        )
        external = backend.all_sessions(
            mock.MagicMock(query={}, remote_addr="8.8.8.8")
        )
        self.assertEqual(backend_local["Sessions"][0]["IpAddress"], "1.1.1.1")
        self.assertEqual(external["Sessions"][0]["IpAddress"], "1.1.1.1")

    def test_remote_backend_preserves_a_public_address_reported_by_server(self):
        created = backend.create_session(
            {"IpAddress": "9.9.9.9", "Port": 7777}, "1.1.1.1"
        )

        self.assertEqual(created["IpAddress"], "9.9.9.9")
        self.assertEqual(
            backend.STATE["sessions"][created["SessionId"]]["_advertise_mode"],
            "reported",
        )

    def test_keepalive_upgrades_a_legacy_remote_session(self):
        created = backend.create_session(
            {"IpAddress": "192.168.1.76", "Port": 7777}, "127.0.0.1"
        )
        self.assertEqual(created["IpAddress"], "192.168.1.76")

        refreshed = backend.keep_alive(created["SessionId"], "1.1.1.1")

        self.assertEqual(refreshed["IpAddress"], "1.1.1.1")
        self.assertEqual(
            backend.STATE["sessions"][created["SessionId"]]["_advertise_mode"],
            "detected",
        )

    def test_server_prefix_can_create_and_list_session(self):
        _, created = self.request(
            "/r/abcd/s/CreateSession",
            {"OwningUserName": "test", "IpAddress": "192.0.2.1", "Port": 7777},
            "POST",
        )
        self.assertEqual(created["SessionId"], "1")
        _, listed = self.request("/r/abcd/p/GetAllSessions")
        self.assertEqual(len(listed["Sessions"]), 1)

        # El servidor manda KeepAlive cada unos 10 segundos. Una sesión reciente
        # no debe caducar durante una carga normal.
        backend.STATE["sessions"]["1"]["_last_seen"] = time.time()
        self.assertFalse(backend.prune_sessions())
        _, listed = self.request("/r/abcd/p/GetAllSessions")
        self.assertEqual(len(listed["Sessions"]), 1)

        self.request(
            "/r/abcd/s/RegisterPlayers",
            {"SessionId": "1", "Players": ["STEAM_12345"]},
            "PATCH",
        )
        _, status = self.request("/r/abcd/s/AdminStatus")
        self.assertEqual(status["api_version"], 1)
        self.assertEqual(status["players"][0]["player_id"], "12345")
        self.request(
            "/r/abcd/s/UnregisterPlayers",
            {"SessionId": "1", "Players": ["STEAM_12345"]},
            "PATCH",
        )
        _, status = self.request("/r/abcd/s/AdminStatus")
        self.assertEqual(status["players"], [])

    def test_session_without_keepalive_expires(self):
        backend.STATE["sessions"]["dead"] = {
            "SessionId": "dead",
            "OwningUserName": "apagado",
            "_last_seen": time.time() - backend.SESSION_TTL - 1,
        }
        self.assertTrue(backend.prune_sessions())
        self.assertNotIn("dead", backend.STATE["sessions"])

    def test_restart_replaces_the_same_server_advertisement(self):
        advertisement = {
            "OwningUserName": "test",
            "IpAddress": "192.0.2.1",
            "Port": 7777,
            "Settings": {
                "MARS_SERVERID": {"Type": "String", "Value": "world_01"}
            },
        }
        _, first = self.request(
            "/r/abcd/s/CreateSession", advertisement, "POST"
        )
        backend.STATE["sessions"]["stale-duplicate"] = dict(
            backend.STATE["sessions"][first["SessionId"]]
        )
        backend.STATE["sessions"]["stale-duplicate"]["SessionId"] = "stale-duplicate"
        _, second = self.request(
            "/r/abcd/s/CreateSession", advertisement, "POST"
        )
        _, listed = self.request("/r/abcd/p/GetAllSessions")

        self.assertEqual(first["SessionId"], second["SessionId"])
        self.assertEqual(len(listed["Sessions"]), 1)


class ManagerTests(unittest.TestCase):
    def test_managed_launch_applies_server_openssl_environment(self):
        settings = {
            "server_dir": "C:/server",
            "server_openssl_compat": True,
        }
        process = mock.Mock(pid=123)
        with (
            mock.patch("server_manager._restore_system_dll_search"),
            mock.patch("server_manager.subprocess.Popen", return_value=process) as popen,
        ):
            result = server_manager._launch_server_process(settings)

        self.assertIs(result, process)
        self.assertEqual(
            popen.call_args.kwargs["env"]["OPENSSL_ia32cap"], ":~0x20000000"
        )

    def test_managed_world_exit_triggers_automatic_restart(self):
        manager = server_manager.ServerManager.__new__(server_manager.ServerManager)
        manager.starting = False
        manager.stopping = False
        manager.auto_restarting = False
        manager.last_auto_restart_at = 0.0
        manager.status_var = mock.Mock()
        manager.status_label = mock.Mock()
        manager.log = mock.Mock()
        manager._auto_restart_world = mock.Mock()
        manager._saved_process_matches = mock.Mock(side_effect=[False, True])
        runtime = {"server_pid": 101, "backend_pid": 202}

        with (
            mock.patch.object(server_manager, "_read_runtime", return_value=runtime),
            mock.patch.object(server_manager.threading, "Thread") as thread,
        ):
            manager._watch_managed_server()

        self.assertTrue(manager.auto_restarting)
        manager.status_var.set.assert_called_once_with("Restarting world...")
        thread.assert_called_once_with(
            target=manager._auto_restart_world, args=(runtime,), daemon=True
        )
        thread.return_value.start.assert_called_once_with()

    def test_server_log_maps_account_to_character_name(self):
        manager = server_manager.ServerManager.__new__(server_manager.ServerManager)
        manager.character_names = {}

        manager._learn_character_names(
            "LogMarsPlayer: (76561198000000001) Spawn of previous Character "
            "for TestPilot (Login) - Fetching previous inventory and health"
        )

        self.assertEqual(manager.character_names["76561198000000001"], "TestPilot")

    def test_detects_an_occupied_backend_port(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            self.assertTrue(server_manager._port_is_listening(listener.getsockname()[1]))

    def test_rejects_generic_response_from_old_backend(self):
        manager = object.__new__(server_manager.ServerManager)
        manager.settings = {"backend_port": 8080, "access_key": "abcd"}
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = b'{"result":"ok"}'
        with (
            mock.patch("server_manager.urllib.request.urlopen", return_value=response),
            self.assertRaises(server_manager.IncompatibleBackendError),
        ):
            manager._fetch_status()


class NativeServerTests(unittest.TestCase):
    def test_server_keeps_its_key_when_client_destination_changes(self):
        stored = {
            **momlib.default_settings(),
            "access_key": "ownserver",
            "server_access_key": "ownserver",
            "client_access_key": "theirkey",
            "server_backend_port": 8080,
            "client_backend_port": 9090,
        }
        options = native_server.build_parser().parse_args(["--prepare-only"])
        with mock.patch("native_server.momlib.load_settings", return_value=stored):
            settings = native_server._settings_from_options(options)

        self.assertEqual(settings["access_key"], "ownserver")
        self.assertEqual(settings["backend_port"], 8080)
        self.assertEqual(settings["client_access_key"], "theirkey")
        self.assertEqual(settings["client_backend_port"], 9090)

    @unittest.skipUnless(os.name == "posix", "POSIX-only process control")
    def test_linux_world_restarts_after_a_normal_exit(self):
        first = mock.MagicMock()
        first.wait.return_value = 0
        second = mock.MagicMock()
        second.pid = 4321
        second.wait.side_effect = [KeyboardInterrupt(), 143]
        settings = {"server_dir": "/server", "server_openssl_compat": True}
        with (
            mock.patch(
                "native_server.momlib.server_launch_spec",
                return_value=(
                    ["/server/MemoriesOfMarsServer", "Game", "-log"],
                    Path("/server"),
                    momlib.LINUX_SERVER_LAYOUT,
                ),
            ),
            mock.patch(
                "native_server.subprocess.Popen", side_effect=[first, second]
            ) as popen,
            mock.patch("native_server.time.sleep") as sleep,
            mock.patch("native_server.os.killpg") as killpg,
        ):
            result = native_server._run_server(settings, [], auto_restart=True)

        self.assertEqual(result, 143)
        self.assertEqual(popen.call_count, 2)
        sleep.assert_called_once_with(10)
        killpg.assert_called_once_with(4321, native_server.signal.SIGTERM)

    @unittest.skipUnless(os.name == "posix", "POSIX-only process isolation")
    def test_backend_is_isolated_until_the_world_has_stopped(self):
        settings = {"backend_port": 8080}
        process = mock.MagicMock()
        process.poll.return_value = None
        with (
            mock.patch("native_server._compatible_backend", side_effect=[False, True]),
            mock.patch("native_server._port_is_listening", return_value=False),
            mock.patch("native_server._backend_command", return_value=["backend"]),
            mock.patch("native_server.subprocess.Popen", return_value=process) as popen,
            mock.patch("native_server.time.sleep"),
        ):
            self.assertIs(native_server._start_backend(settings), process)

        popen.assert_called_once_with(["backend"], start_new_session=True)

    def test_prepare_uses_compatibility_only(self):
        settings = {
            "server_dir": "C:/server",
            "server_backend_host": "127.0.0.1",
            "backend_port": 8080,
            "access_key": "abcd",
            "skip_cloning": True,
        }
        with mock.patch(
            "native_server.momlib.apply_server_compatibility",
            return_value={"url": "http://127.0.0.1", "config": "server.cfg"},
        ) as apply_compatibility:
            native_server._prepare(settings)

        apply_compatibility.assert_called_once_with(
            "C:/server", "127.0.0.1", 8080, "abcd", skip_cloning=True
        )

    def test_restore_is_available_from_the_standalone_launcher(self):
        settings = {"server_dir": "/server"}
        with (
            mock.patch("native_server._settings_from_options", return_value=settings),
            mock.patch("native_server.momlib.save_settings") as save_settings,
            mock.patch(
                "native_server.momlib.restore_server",
                return_value={"binary_restored": True},
            ) as restore_server,
        ):
            self.assertEqual(native_server.main(["--restore"]), 0)

        save_settings.assert_called_once_with(settings)
        restore_server.assert_called_once_with("/server")


class LinuxClientTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX-only CPU affinity")
    def test_proton_affinity_is_restored_after_loading(self):
        process = mock.MagicMock(pid=4321)
        timer = mock.MagicMock()
        settings = {
            "linux_limit_client_cpu": True,
            "client_load_cores": 4,
            "client_load_seconds": 75,
        }
        with (
            mock.patch(
                "linux_client.os.sched_getaffinity",
                return_value=set(range(2, 14)),
            ),
            mock.patch("linux_client.os.sched_setaffinity") as set_affinity,
            mock.patch("linux_client.threading.Timer", return_value=timer) as create_timer,
        ):
            result = linux_client._limit_cpu_during_load(
                process, Path("/compat"), settings
            )

        self.assertIs(result, timer)
        set_affinity.assert_called_once_with(4321, [2, 3, 4, 5])
        create_timer.assert_called_once_with(
            75,
            linux_client._restore_prefix_affinity,
            args=(4321, Path("/compat"), list(range(2, 14))),
        )
        self.assertTrue(timer.daemon)
        timer.start.assert_called_once_with()

    @unittest.skipUnless(os.name == "posix", "POSIX-only CPU affinity")
    def test_proton_cpu_limit_is_disabled_by_default(self):
        process = mock.MagicMock(pid=4321)
        with mock.patch("linux_client.os.sched_setaffinity") as set_affinity:
            result = linux_client._limit_cpu_during_load(
                process, Path("/compat"), {}
            )

        self.assertIsNone(result)
        set_affinity.assert_not_called()

    def test_proton_client_uses_the_prefix_windows_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            compat = Path(tmp) / "compatdata/644290"
            local = compat / "pfx/drive_c/users/steamuser/AppData/Local"
            local.mkdir(parents=True)

            self.assertEqual(
                linux_client._client_ini(compat),
                local / "MemoriesOfMars/Saved/Config/WindowsNoEditor/Engine.ini",
            )

    @unittest.skipUnless(os.name == "posix", "POSIX-only Proton process control")
    def test_proton_launch_bypasses_eac(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = root / "steamapps/common/Memories of Mars"
            exe = client / momlib.CLIENT_EXE_REL
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"MZ")
            proton = root / "steamapps/common/Proton/proton"
            proton.parent.mkdir(parents=True)
            proton.write_text("", encoding="utf-8")
            compat = root / "steamapps/compatdata/644290"
            process = mock.MagicMock()
            process.pid = 9876
            process.wait.return_value = 0
            with (
                mock.patch("linux_client.subprocess.Popen", return_value=process) as popen,
                mock.patch("linux_client.os.cpu_count", return_value=4),
            ):
                result = linux_client._launch(
                    client,
                    compat,
                    proton,
                    {"limit_client_cpu": True},
                    ["-windowed"],
                )

            self.assertEqual(result, 0)
            command = popen.call_args.args[0]
            self.assertEqual(command[0:2], [str(proton), "run"])
            self.assertIn("-NoEAC", command)
            self.assertIn("-windowed", command)
            env = popen.call_args.kwargs["env"]
            self.assertEqual(env["SteamAppId"], "644290")
            self.assertEqual(env["STEAM_COMPAT_DATA_PATH"], str(compat))
            self.assertEqual(env["PROTON_DISABLE_NVAPI"], "1")

    def test_nvapi_can_be_explicitly_enabled(self):
        parser = linux_client.build_parser()
        self.assertFalse(parser.parse_args(["--enable-nvapi"]).disable_nvapi)
        self.assertTrue(parser.parse_args(["--disable-nvapi"]).disable_nvapi)

    def test_dead_game_process_stops_the_remaining_prefix(self):
        process = mock.MagicMock(pid=9876)
        process.poll.return_value = None
        stop_event = mock.MagicMock()
        stop_event.wait.side_effect = [False, False]
        with (
            mock.patch(
                "linux_client._prefix_processes",
                side_effect=[[100], [100]],
            ),
            mock.patch(
                "linux_client._process_identity",
                side_effect=[("memoriesofmars.exe", "S"), ("", "")],
            ),
            mock.patch("linux_client._stop_prefix_processes") as stop_prefix,
        ):
            linux_client._watch_game_process(
                process, Path("/compat"), stop_event, interval=0
            )

        stop_prefix.assert_called_once_with(process, Path("/compat"))

    @unittest.skipUnless(hasattr(os, "killpg"), "POSIX-only process groups")
    def test_prefix_cleanup_escalates_when_wine_ignores_sigterm(self):
        process = mock.MagicMock(pid=9876)
        with (
            mock.patch(
                "linux_client._prefix_processes",
                side_effect=[[100], [100]],
            ),
            mock.patch(
                "linux_client._process_identity",
                return_value=("wineserver", "S"),
            ),
            mock.patch("linux_client.os.kill") as kill,
            mock.patch("linux_client.os.killpg") as killpg,
        ):
            linux_client._stop_prefix_processes(
                process, Path("/compat"), grace_seconds=0
            )

        self.assertEqual(
            kill.call_args_list,
            [mock.call(100, signal.SIGTERM), mock.call(100, signal.SIGKILL)],
        )
        self.assertEqual(
            killpg.call_args_list,
            [
                mock.call(9876, signal.SIGTERM),
                mock.call(9876, signal.SIGKILL),
            ],
        )

    def test_foreign_server_key_does_not_replace_local_server_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client_dir = root / "client"
            exe = client_dir / momlib.CLIENT_EXE_REL
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"MZ")
            compat = root / "compatdata/644290"
            proton = root / "Proton/proton"
            saved = {}
            settings = {
                "access_key": "ownserver",
                "server_access_key": "ownserver",
                "backend_port": 8080,
            }
            with (
                mock.patch("linux_client.momlib.load_settings", return_value=settings),
                mock.patch(
                    "linux_client.momlib.discover_installs",
                    return_value=(client_dir, None),
                ),
                mock.patch("linux_client._compat_root", return_value=compat),
                mock.patch("linux_client._proton_path", return_value=proton),
                mock.patch("linux_client.momlib.save_settings", side_effect=lambda value: saved.update(value)),
                mock.patch(
                    "linux_client.momlib.apply_client",
                    return_value={"url": "http://other.example/r/theirkey/p/"},
                ),
            ):
                result = linux_client.main(
                    [
                        "--prepare-only",
                        "--host",
                        "other.example",
                        "--port",
                        "9090",
                        "--key",
                        "theirkey",
                    ]
                )

            self.assertEqual(result, 0)
            self.assertEqual(saved["server_access_key"], "ownserver")
            self.assertEqual(saved["access_key"], "ownserver")
            self.assertEqual(saved["client_access_key"], "theirkey")
            self.assertEqual(saved["client_backend_port"], 9090)


class LinuxConfigureTests(unittest.TestCase):
    def test_no_arguments_open_the_server_wizard(self):
        with mock.patch("linux_configure.server_wizard", return_value=0) as wizard:
            result = linux_configure.main([])

        self.assertEqual(result, 0)
        wizard.assert_called_once_with()

    def test_server_wizard_prepares_a_public_server(self):
        settings = {
            "server_dir": "/srv/mom",
            "backend_port": 8080,
            "access_key": "deadbeef",
            "public_ip": "",
        }
        with (
            mock.patch("linux_configure.momlib.load_settings", return_value=settings),
            mock.patch(
                "linux_configure.momlib.discover_installs",
                return_value=(None, Path("/detected/server")),
            ),
            mock.patch(
                "linux_configure._validate_server_dir", return_value="/srv/mom"
            ),
            mock.patch(
                "linux_configure.momlib.detect_public_ip",
                return_value="203.0.113.20",
            ),
            mock.patch("linux_configure._service_available", return_value=False),
            mock.patch("linux_configure.native_server.main", return_value=0) as server,
            mock.patch("builtins.input", side_effect=["", "", "", "", ""]),
        ):
            result = linux_configure.server_wizard()

        self.assertEqual(result, 0)
        args = server.call_args.args[0]
        self.assertEqual(args[args.index("--server-dir") + 1], "/srv/mom")
        self.assertEqual(args[args.index("--backend-host") + 1], "127.0.0.1")
        self.assertEqual(args[args.index("--bind") + 1], "0.0.0.0")
        self.assertEqual(args[args.index("--port") + 1], "8080")
        self.assertEqual(args[args.index("--key") + 1], "deadbeef")
        self.assertEqual(args[args.index("--public-ip") + 1], "203.0.113.20")

    def test_shared_contract_is_forwarded_to_client_and_server(self):
        settings = {
            "client_backend_host": "relive.example",
            "client_backend_port": 9000,
            "client_access_key": "samekey",
        }
        with (
            mock.patch("linux_configure.native_server.main", return_value=0) as server,
            mock.patch("linux_configure.linux_client.main", return_value=0) as client,
            mock.patch("linux_configure.momlib.load_settings", return_value=settings),
        ):
            result = linux_configure.main(
                [
                    "--host",
                    "relive.example",
                    "--port",
                    "9000",
                    "--key",
                    "samekey",
                    "--server-dir",
                    "/server",
                    "--client-dir",
                    "/client",
                    "--compat-dir",
                    "/compat",
                ]
            )

        self.assertEqual(result, 0)
        server_args = server.call_args.args[0]
        client_args = client.call_args.args[0]
        self.assertEqual(server_args[server_args.index("--key") + 1], "samekey")
        self.assertEqual(client_args[client_args.index("--key") + 1], "samekey")
        self.assertEqual(server_args[server_args.index("--port") + 1], "9000")
        self.assertEqual(client_args[client_args.index("--port") + 1], "9000")


class LinuxInstallerTests(unittest.TestCase):
    def test_systemd_sigint_shutdown_is_treated_as_success(self):
        installer = Path(__file__).resolve().parents[1] / "install_linux.sh"
        service_lines = installer.read_text(encoding="utf-8")

        self.assertIn("'KillSignal=SIGINT'", service_lines)
        self.assertIn("'SuccessExitStatus=130'", service_lines)

    def test_linux_release_includes_public_server_guide(self):
        root = Path(__file__).resolve().parents[1]
        build_script = (root / "build_release_linux.sh").read_text(encoding="utf-8")

        self.assertTrue((root / "PUBLIC-SERVER.md").is_file())
        self.assertIn(
            'install -m 644 PUBLIC-SERVER.md "$package_dir/PUBLIC-SERVER.md"',
            build_script,
        )

    def test_release_installers_require_complete_legal_notices(self):
        root = Path(__file__).resolve().parents[1]
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                root / "build_release_linux.sh",
                root / "build_release.ps1",
                root / "install_linux.sh",
                root / "installer/MoMRevival.iss",
            )
        )
        for notice in (
            "LEGAL.md",
            "LICENSE",
            "COPYRIGHT",
            "THIRD-PARTY-NOTICES.md",
            "PYTHON-LICENSE.txt",
            "PYINSTALLER-LICENSE.txt",
        ):
            self.assertIn(notice, source)
        self.assertIn("TCL-TK-LICENSE.txt", source)
        self.assertIn("INNO-SETUP-LICENSE.txt", source)


if __name__ == "__main__":
    unittest.main()
