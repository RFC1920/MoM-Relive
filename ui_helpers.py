"""Small controls shared by the desktop applications."""

from __future__ import annotations


class ToolTip:
    """Ayuda breve al mantener el puntero sobre un control."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.after_id = None
        self.window = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._hide()
        self.after_id = self.widget.after(450, self._show)

    def _show(self):
        import tkinter as tk

        if self.window or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_pointerx() + 14
        y = self.widget.winfo_pointery() + 18
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self.window,
            text=self.text,
            justify="left",
            background="#fffbd6",
            foreground="#202020",
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=5,
            wraplength=360,
        ).pack()

    def _hide(self, _event=None):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None
        if self.window:
            self.window.destroy()
            self.window = None
