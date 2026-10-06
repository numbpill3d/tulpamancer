"""Small lower-left desktop companion for sending messages to Tulpa."""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

from utils.voice import VoiceInput


ROOT = Path(__file__).resolve().parent.parent
BLACK = "#050507"
PANEL = "#0b0b0f"
RED = "#d51f3f"
RED_DIM = "#6d1025"
WHITE = "#f4e9ec"
MUTED = "#a36b77"


class TulpaWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Tulpa")
        self.root.geometry("300x445")
        self.root.minsize(280, 390)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=RED)
        self.busy = False
        self.events: queue.Queue[str] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.voice = VoiceInput()

        self._place_lower_left()
        self._build()
        self._poll_events()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _place_lower_left(self):
        self.root.update_idletasks()
        height = self.root.winfo_screenheight()
        self.root.geometry(f"300x445+18+{height - 505}")

    def _build(self):
        header = tk.Frame(self.root, bg=BLACK, padx=10, pady=8)
        header.pack(fill="x", padx=2, pady=2)
        portrait = tk.Canvas(
            header, width=38, height=38, bg=BLACK, highlightthickness=1, highlightbackground=RED_DIM
        )
        portrait.pack(side="left", padx=(0, 9))
        portrait.create_oval(6, 6, 32, 32, fill=RED_DIM, outline=RED, width=2)
        portrait.create_oval(13, 14, 16, 18, fill=BLACK, outline="")
        portrait.create_oval(23, 14, 26, 18, fill=BLACK, outline="")
        portrait.create_arc(12, 15, 27, 29, start=200, extent=140, outline=BLACK, width=2)

        title = tk.Frame(header, bg=BLACK)
        title.pack(side="left", fill="x")
        tk.Label(
            title, text="TULPA // EDGEFRIEND", fg=WHITE, bg=BLACK, font=("TkFixedFont", 10, "bold")
        ).pack(anchor="w")
        tk.Label(title, text="● LINKED / LIVE2D", fg=RED, bg=BLACK, font=("TkFixedFont", 8)).pack(
            anchor="w"
        )

        self.transcript = tk.Text(
            self.root,
            bg=PANEL,
            fg=WHITE,
            insertbackground=RED,
            relief="flat",
            highlightthickness=1,
            highlightbackground=RED_DIM,
            wrap="word",
            padx=9,
            pady=9,
            font=("TkFixedFont", 9),
            state="disabled",
        )
        self.transcript.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        self.transcript.tag_configure("you", foreground="#ff8298")
        self.transcript.tag_configure("tulpa", foreground=WHITE)
        self.transcript.tag_configure("status", foreground=MUTED)
        self._append("status", "Tulpa is listening.\n")

        controls = tk.Frame(self.root, bg=BLACK, padx=8)
        controls.pack(fill="x", pady=(0, 6))
        self.obs_status = tk.Label(
            controls, text="OBS ?", fg=MUTED, bg=BLACK, font=("TkFixedFont", 8, "bold")
        )
        self.obs_status.pack(side="left")
        for label, action in (
            ("CHECK", self.check_obs),
            ("START", self.start_obs),
            ("STOP", self.stop_obs),
            ("E-STOP", self.emergency_stop),
        ):
            tk.Button(
                controls,
                text=label,
                command=action,
                bg=BLACK,
                fg=RED,
                activebackground=RED_DIM,
                activeforeground=WHITE,
                relief="flat",
                bd=0,
                font=("TkFixedFont", 7, "bold"),
            ).pack(side="right", padx=(4, 0))

        composer = tk.Frame(self.root, bg=BLACK, padx=8, pady=0)
        composer.pack(fill="x", pady=(0, 8))
        self.entry = tk.Entry(
            composer,
            bg=PANEL,
            fg=WHITE,
            insertbackground=RED,
            relief="flat",
            highlightthickness=1,
            highlightbackground=RED_DIM,
            font=("TkFixedFont", 10),
        )
        self.entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))
        self.entry.bind("<Return>", lambda _event: self.send())
        self.send_button = tk.Button(
            composer,
            text="↗",
            command=self.send,
            bg=RED_DIM,
            fg=WHITE,
            activebackground=RED,
            activeforeground=WHITE,
            relief="flat",
            bd=0,
            font=("TkFixedFont", 11, "bold"),
            width=3,
        )
        self.send_button.pack(side="right", ipady=2)
        self.mic_button = tk.Button(
            composer,
            text="MIC",
            command=self.toggle_voice,
            bg=BLACK,
            fg=RED,
            activebackground=RED_DIM,
            activeforeground=WHITE,
            relief="flat",
            bd=0,
            font=("TkFixedFont", 8, "bold"),
        )
        self.mic_button.pack(side="right", padx=(0, 6), ipady=4)
        self.entry.focus_set()
        self.root.after(500, self.check_obs)

    def _append(self, tag: str, text: str):
        self.transcript.configure(state="normal")
        self.transcript.insert("end", text, tag)
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    def send(self):
        message = self.entry.get().strip()
        if not message or self.busy:
            return
        self.entry.delete(0, "end")
        self._append("you", f"YOU › {message}\n")
        self.busy = True
        self.send_button.configure(state="disabled", text="...")
        threading.Thread(target=self._speak, args=(message,), daemon=True).start()

    def _obs_command(self, action: str):
        try:
            result = subprocess.run(
                [sys.executable, str(ROOT / "src/main.py"), action],
                cwd=ROOT,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                timeout=12,
            )
            output = (result.stdout or result.stderr).strip().splitlines()
            self.events.put(("obs", output[-1] if output else "OBS command failed"))
        except Exception as exc:
            self.events.put(("obs", f"OBS {type(exc).__name__}"))

    def check_obs(self):
        threading.Thread(target=self._obs_command, args=("--obs-status",), daemon=True).start()

    def start_obs(self):
        if messagebox.askyesno("Start OBS stream", "Start the configured OBS broadcast now?"):
            threading.Thread(
                target=self._obs_command, args=("--start-stream",), daemon=True
            ).start()

    def stop_obs(self):
        threading.Thread(target=self._obs_command, args=("--stop-stream",), daemon=True).start()

    def emergency_stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
        self._append("status", "EMERGENCY STOP — speech process terminated.\n")
        threading.Thread(target=self._obs_command, args=("--stop-stream",), daemon=True).start()

    def toggle_voice(self):
        if self.busy:
            return
        if not self.voice.recording:
            try:
                self.voice.start()
                self.mic_button.configure(text="STOP", fg=WHITE, bg=RED_DIM)
                self._append("status", "Listening… press STOP when finished.\n")
            except Exception as exc:
                self._append("status", f"[mic] {type(exc).__name__}\n")
            return
        self.mic_button.configure(state="disabled", text="...")
        threading.Thread(target=self._transcribe, daemon=True).start()

    def _transcribe(self):
        try:
            text = self.voice.stop_and_transcribe()
            self.events.put(("voice", text))
        except Exception as exc:
            self.events.put(("status", f"[mic] {type(exc).__name__}\n"))
            self.events.put(("voice", ""))

    def _speak(self, message: str):
        command = [
            sys.executable,
            str(ROOT / "src/main.py"),
            "--message",
            message,
            "--utterances",
            "1",
        ]
        try:
            self.process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=os.environ.copy(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                if line.startswith("[Tulpa]"):
                    self.events.put(("tulpa", line))
                elif line.startswith("[error]") or "unavailable" in line:
                    self.events.put(("status", line))
            self.process.wait()
        except Exception as exc:
            self.events.put(("status", f"[window] {type(exc).__name__}\n"))
        finally:
            self.events.put(("ready", ""))

    def _poll_events(self):
        try:
            while True:
                tag, text = self.events.get_nowait()
                if tag == "ready":
                    self.busy = False
                    self.send_button.configure(state="normal", text="SEND")
                elif tag == "voice":
                    self.mic_button.configure(state="normal", text="MIC", fg=RED, bg=BLACK)
                    if text:
                        self.entry.insert(0, text)
                        self.send()
                    else:
                        self._append("status", "[mic] I didn’t catch that.\n")
                elif tag == "obs":
                    self.obs_status.configure(
                        text="OBS LIVE"
                        if "streaming=True" in text
                        else "OBS READY"
                        if "streaming=False" in text
                        else "OBS ?",
                        fg=RED if "streaming=True" in text else MUTED,
                    )
                    self._append("status", f"{text}\n")
                else:
                    self._append(tag, text)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
        self.root.destroy()


def main():
    root = tk.Tk()
    TulpaWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
