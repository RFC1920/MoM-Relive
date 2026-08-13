# Legal notice

Last updated: 13 August 2026

This document describes the intended scope of MoM Relive. It is provided for
information only and is not legal advice.

## Unofficial community project

MoM Relive is an independently developed, unofficial community compatibility
project. It is not endorsed by, sponsored by, or affiliated with 505 Games,
Limbic Entertainment, Valve, Epic Games, Easy Anti-Cheat, or their respective
affiliates.

Nothing in this notice asserts that a rightsholder has approved the project or
waived any right. Describing the project's intended purpose is not a legal
determination that every use is permitted in every jurisdiction or under every
applicable agreement.

Memories of Mars and its name and logos are trademarks or other protected
properties of their respective owners. Their names are used only to identify
the software with which MoM Relive is intended to interoperate. MoM Relive does
not claim ownership of those names, logos, the game, or any game content.

## Requirements and distribution

Users must obtain and use a legitimate copy of Memories of Mars and, when
hosting, its dedicated-server software. MoM Relive does not grant a licence to
the game or to any third-party software.

The project and its installer do not include or redistribute game executables,
game assets, Steam files, Easy Anti-Cheat files, saved games, product keys, or
patched copies of third-party binaries. Compatibility changes are applied on
the user's computer to files from the user's own installation. The tools keep
recoverable baselines so that managed changes can be reversed.

## Interoperability and permitted use

MoM Relive provides independently authored tools and replacement services for
community-hosted play following the shutdown of the original online services.
No original game source code or decompiled game code is included in this
repository. Compatibility behaviour was determined by observing and analysing
lawfully obtained software and network interactions, and is implemented only
to the extent considered necessary for interoperability.

The project is intended only for private or community servers whose operators
and players have chosen to use it. It is not intended to connect to official
services, to interfere with servers that require anti-cheat protection, to
obtain a competitive advantage, to facilitate piracy, or to bypass product
ownership and licence checks.

The community compatibility mode does not use Easy Anti-Cheat because the
retired service environment it replaces is separate from active or official
anti-cheat-protected play. MoM Relive does not include or modify Easy
Anti-Cheat files. Users must not use the project against any service or server
without the operator's permission.

Users are responsible for confirming that their possession and use of the
game, the dedicated server, and MoM Relive comply with applicable law,
agreements, and platform rules in their jurisdiction.

The project must not be used to bypass purchase, ownership, subscription,
licence-key, entitlement, or access controls. It must not be represented as an
official continuation of the game or its services. Operators should stop use
and seek qualified legal advice if a rightsholder objects to a specific use.

## Privacy and server operation

The MoM Relive project does not operate a central account, matchmaking, or
telemetry service. A server administrator runs the replacement backend and
retains its data locally or on infrastructure chosen by that administrator.

The server tools may process and record player identifiers, character names,
network addresses, session information, request data, and operational logs.
Server administrators are responsible for securing that information, limiting
retention, informing their users when required, and complying with applicable
privacy and data-protection law.

When the server manager automatically detects a public IP address, it makes an
HTTPS request to `https://api.ipify.org`. That external service receives the
requesting public IP address and is governed by its own terms and privacy
practices. Administrators may instead enter a public IP address or DNS name
manually.

## No warranty

MoM Relive is experimental software provided without any warranty. It can
modify local configuration and executable files, open firewall ports, launch
network services, and manage saved-game data. Users should keep independent
backups and review the source and configuration before exposing a server to the
Internet.

To the extent permitted by applicable law, the contributors are not liable for
loss of data, account or platform action, service interruption, security
incidents, or other damage resulting from use of the project.

## Project licence

The GNU General Public License v3.0 in [LICENSE](LICENSE) applies only to the
original project code and contributions covered by that licence. It does not
grant rights to Memories of Mars, its trademarks, third-party software, or any
other material owned by their respective rightsholders.

Project copyright attribution is recorded in [COPYRIGHT](COPYRIGHT). Binary
packages also contain [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) and the
complete licence texts for the runtime components embedded by that build.
The corresponding source for each binary release is available from the tag
with the same version at <https://github.com/drbermejor/MoM-Relive>.

## Rightsholder contact

Rightsholders who believe that material in this repository affects their
rights are encouraged to contact the repository owner through GitHub and
identify the specific material and right concerned. Do not publish personal or
confidential information in a public issue.
