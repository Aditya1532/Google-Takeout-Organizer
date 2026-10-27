"""Beginner-friendly desktop interface for Google Takeout Organizer."""
import os
import threading
import time
import ctypes
import uuid
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from organizer import Candidate, OperationLog, classify, copy_batch_verified, folder_size_bytes, index_existing_files_by_name, indices_without_output_name_match, preflight_destination_space, remove_sources_after_verified, scan, undo_last


def _select_multiple_folders(owner_hwnd=0):
    """Show the Windows Explorer folder picker with Ctrl/Shift multi-select."""
    if os.name != "nt":
        one = filedialog.askdirectory(title="Choose a folder to scan")
        return [one] if one else []

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                    ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

        @classmethod
        def from_string(cls, value):
            return cls.from_buffer_copy(uuid.UUID(value).bytes_le)

    def call(interface, index, restype, argtypes, *args):
        vtable = ctypes.cast(interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        function = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])
        return function(interface, *args)

    ole32 = ctypes.OleDLL("ole32")
    ole32.CoInitialize.argtypes = [ctypes.c_void_p]
    ole32.CoInitialize.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None
    ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, ctypes.c_uint32,
                                       ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    ole32.CoCreateInstance.restype = ctypes.c_long

    clsid_dialog = GUID.from_string("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")
    iid_dialog = GUID.from_string("D57C7288-D4AD-4768-BE02-9D969532D960")
    dialog = ctypes.c_void_p()
    initialized = False
    try:
        hr = ole32.CoInitialize(None)
        if hr < 0: raise OSError(f"COM initialization failed (0x{hr & 0xFFFFFFFF:08X})")
        initialized = True
        hr = ole32.CoCreateInstance(ctypes.byref(clsid_dialog), None, 1, ctypes.byref(iid_dialog), ctypes.byref(dialog))
        if hr < 0: raise OSError(f"Could not open the Windows folder picker (0x{hr & 0xFFFFFFFF:08X})")
        options = ctypes.c_uint32()
        hr = call(dialog, 10, ctypes.c_long, [ctypes.POINTER(ctypes.c_uint32)], ctypes.byref(options))
        if hr < 0: raise OSError("Could not configure the Windows folder picker")
        flags = options.value | 0x20 | 0x40 | 0x200 | 0x800 | 0x8  # pick folders, filesystem paths, multiselect
        hr = call(dialog, 9, ctypes.c_long, [ctypes.c_uint32], flags)
        if hr < 0: raise OSError("Could not enable multi-folder selection")
        call(dialog, 17, ctypes.c_long, [ctypes.c_wchar_p], "Select folders to scan (Ctrl-click or Shift-click for multiple)")
        call(dialog, 18, ctypes.c_long, [ctypes.c_wchar_p], "Add selected folders")
        hr = call(dialog, 3, ctypes.c_long, [ctypes.c_void_p], owner_hwnd)
        if (hr & 0xFFFFFFFF) == 0x800704C7: return []  # User cancelled
        if hr < 0: raise OSError(f"Folder selection failed (0x{hr & 0xFFFFFFFF:08X})")

        items = ctypes.c_void_p()
        hr = call(dialog, 27, ctypes.c_long, [ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(items))
        if hr < 0: raise OSError("Could not read the selected folders")
        paths = []
        try:
            count = ctypes.c_uint32()
            hr = call(items, 7, ctypes.c_long, [ctypes.POINTER(ctypes.c_uint32)], ctypes.byref(count))
            if hr < 0: raise OSError("Could not count the selected folders")
            for i in range(count.value):
                shell_item = ctypes.c_void_p()
                hr = call(items, 8, ctypes.c_long, [ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)], i, ctypes.byref(shell_item))
                if hr < 0: continue
                try:
                    display_name = ctypes.c_wchar_p()
                    hr = call(shell_item, 5, ctypes.c_long, [ctypes.c_uint32, ctypes.POINTER(ctypes.c_wchar_p)], 0x80058000, ctypes.byref(display_name))
                    if hr >= 0 and display_name:
                        paths.append(display_name.value)
                        ole32.CoTaskMemFree(ctypes.cast(display_name, ctypes.c_void_p))
                finally:
                    call(shell_item, 2, ctypes.c_uint32, [])
        finally:
            call(items, 2, ctypes.c_uint32, [])
        return paths
    finally:
        if dialog:
            call(dialog, 2, ctypes.c_uint32, [])
        if initialized:
            ole32.CoUninitialize()

class OrganizerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Google Takeout Organizer")
        root.geometry("1280x760")
        root.minsize(1024, 620)
        self.dark_mode = False
        self.style = ttk.Style(root)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.roots: list[Path] = []
        self.root_sizes: dict[str, int | None] = {}
        self.size_scan_event = threading.Event()
        self.candidates: list[Candidate] = []
        self.existing_output_index: dict[str, list[Path]] = {}
        self.existing_index_destination = ""
        self.replace_row_targets: dict[str, tuple[int, Path]] = {}
        self.cancel_event = threading.Event()
        self.preview_ready = False
        self.operation_running = False
        self.operation_var = tk.StringVar(value="Copy")
        self.destination = tk.StringVar(value=str(Path.home() / "My Organized Files"))
        self.status = tk.StringVar(value="Dry run is active. Nothing will be moved or copied until you choose Apply Changes.")
        self._apply_theme()
        self._build()
        self._apply_theme()
        self.destination.trace_add("write", self._destination_changed)
        self.root.after_idle(self._fit_to_screen)

    def _fit_to_screen(self):
        """Start with the complete organizer visible in one screen-sized window."""
        try:
            if os.name == "nt":
                self.root.state("zoomed")
                return
            width = max(1024, self.root.winfo_screenwidth() - 48)
            height = max(620, self.root.winfo_screenheight() - 80)
            self.root.geometry(f"{width}x{height}+24+24")
        except tk.TclError:
            # Keep the ordinary resizable geometry if this desktop cannot maximize it.
            pass

    def _apply_theme(self):
        """Apply one consistent palette to Tk and themed widgets."""
        if self.dark_mode:
            colors = {
                "window": "#171a21", "surface": "#222733", "surface_alt": "#2b3240",
                "text": "#edf1f7", "muted": "#b7c0ce", "border": "#414a5a",
                "accent": "#65b9ff", "selected": "#235b88", "field": "#1d222c",
                "button": "#303949", "button_active": "#3c485b", "warning": "#ffd166",
            }
        else:
            colors = {
                "window": "#f3f5f8", "surface": "#ffffff", "surface_alt": "#edf1f6",
                "text": "#202733", "muted": "#505b6b", "border": "#c7cfda",
                "accent": "#1264a3", "selected": "#cfe7ff", "field": "#ffffff",
                "button": "#f0f3f7", "button_active": "#e1e8f0", "warning": "#8a5100",
            }
        self.colors = colors
        self.root.configure(background=colors["window"])
        self.style.configure(".", background=colors["window"], foreground=colors["text"],
                             font=("Segoe UI", 9))
        self.style.configure("TFrame", background=colors["window"])
        self.style.configure("TLabel", background=colors["window"], foreground=colors["text"])
        self.style.configure("TLabelframe", background=colors["window"], foreground=colors["text"],
                             bordercolor=colors["border"])
        self.style.configure("TLabelframe.Label", background=colors["window"], foreground=colors["text"])
        self.style.configure("TButton", background=colors["button"], foreground=colors["text"],
                             bordercolor=colors["border"], focusthickness=2, focuscolor=colors["accent"], padding=(8, 4))
        self.style.map("TButton", background=[("disabled", colors["surface_alt"]),
                                               ("active", colors["button_active"])],
                       foreground=[("disabled", colors["muted"])])
        self.style.configure("TEntry", fieldbackground=colors["field"], foreground=colors["text"],
                             insertcolor=colors["text"], bordercolor=colors["border"])
        self.style.configure("TCombobox", fieldbackground=colors["field"], foreground=colors["text"],
                             background=colors["button"], arrowcolor=colors["text"], bordercolor=colors["border"])
        self.style.map("TCombobox", fieldbackground=[("readonly", colors["field"])],
                       foreground=[("readonly", colors["text"])])
        self.style.configure("TNotebook", background=colors["window"], bordercolor=colors["border"])
        self.style.configure("TNotebook.Tab", background=colors["button"], foreground=colors["text"], padding=(10, 5))
        self.style.map("TNotebook.Tab", background=[("selected", colors["surface"]), ("active", colors["button_active"])],
                       foreground=[("selected", colors["text"])])
        self.style.configure("Treeview", background=colors["surface"], fieldbackground=colors["surface"],
                             foreground=colors["text"], bordercolor=colors["border"], rowheight=23)
        self.style.map("Treeview", background=[("selected", colors["selected"])],
                       foreground=[("selected", colors["text"])])
        self.style.configure("Treeview.Heading", background=colors["surface_alt"], foreground=colors["text"],
                             bordercolor=colors["border"])
        self.style.map("Treeview.Heading", background=[("active", colors["button_active"])])
        self.style.configure("TScrollbar", background=colors["button"], troughcolor=colors["window"],
                             arrowcolor=colors["text"], bordercolor=colors["border"])
        self.style.configure("Horizontal.TProgressbar", background=colors["accent"],
                             troughcolor=colors["surface_alt"], bordercolor=colors["border"])
        if hasattr(self, "root_list"):
            self.root_list.configure(background=colors["surface"], foreground=colors["text"],
                                     selectbackground=colors["selected"], selectforeground=colors["text"],
                                     highlightbackground=colors["border"], highlightcolor=colors["accent"])
        if hasattr(self, "theme_button"):
            self.theme_button.configure(text=self._theme_button_label())

    def _theme_button_label(self):
        return "🌙 Dark mode" if self.dark_mode else "☀ Light mode"

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self._apply_theme()

    def _destination_changed(self, *_):
        self.preview_ready = False
        self.existing_output_index = {}
        self.existing_index_destination = ""
        for candidate in self.candidates:
            candidate.replace_existing = False
            candidate.replacement_target = ""

    def _build(self):
        brand = ttk.Frame(self.root, padding=(10, 2, 10, 0))
        brand.pack(fill="x")
        logo_path = Path(__file__).parent / "assets" / "takeout-organizer-logo.png"
        try:
            logo = tk.PhotoImage(file=str(logo_path))
            scale = max(1, (max(logo.width(), logo.height()) + 55) // 56)
            self.logo_image = logo.subsample(scale, scale)
            ttk.Label(brand, image=self.logo_image).pack(side="left", padx=(0, 8))
        except (tk.TclError, OSError):
            self.logo_image = None
        ttk.Label(brand, text="Google Takeout Organizer", font=("Segoe UI", 18, "bold")).pack(side="left", anchor="center")
        self.theme_button = ttk.Button(brand, text=self._theme_button_label(), command=self.toggle_theme)
        self.theme_button.pack(side="right", padx=(8, 0))

        scan_box = ttk.LabelFrame(self.root, text="1. Scan locations — folders whose files you want to organize", padding=5)
        scan_box.pack(fill="x", padx=10, pady=4)
        self.root_list = tk.Listbox(scan_box, height=2, selectmode="extended", exportselection=False)
        root_scroll = ttk.Scrollbar(scan_box, orient="vertical", command=self.root_list.yview)
        self.root_list.configure(yscrollcommand=root_scroll.set)
        self.root_list.pack(side="left", fill="x", expand=True)
        root_scroll.pack(side="left", fill="y", padx=(0, 8))
        root_buttons = ttk.Frame(scan_box); root_buttons.pack(side="left", fill="y")
        ttk.Button(root_buttons, text="Add folder(s) / drive…", command=self.add_root).pack(fill="x", pady=2)
        ttk.Button(root_buttons, text="Remove selected", command=self.remove_roots).pack(fill="x", pady=2)
        self._refresh_roots()
        ttk.Label(scan_box, text="Each folder shows its total file size; calculating this does not copy or organize anything.", padding=(2, 2)).pack(side="bottom", anchor="w")

        output = ttk.LabelFrame(self.root, text="2. Output destination — where organized copies will be saved", padding=5)
        output.pack(fill="x", padx=10, pady=(4, 4))
        self.destination_entry = ttk.Entry(output, textvariable=self.destination)
        self.destination_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(output, text="Choose destination…", command=self.choose_destination).pack(side="left")
        ttk.Button(output, text="Open destination", command=self.open_output).pack(side="left", padx=(6, 0))

        controls = ttk.Frame(self.root, padding=(10, 2)); controls.pack(fill="x")
        for label, cmd in [("Scan", self.scan), ("Analyze files (local rules)", self.analyze), ("Preview Changes", self.preview),
                           ("Apply Changes", self.apply), ("Cancel", self.cancel), ("Undo", self.undo)]:
            ttk.Button(controls, text=label, command=cmd).pack(side="left", padx=3)
        ttk.Label(controls, text="DRY RUN · no file changes until Apply Changes", foreground="#a05a00", font=("Segoe UI", 10, "bold")).pack(side="right", padx=8)
        self.tabs = ttk.Notebook(self.root)
        self.preview_tab = ttk.Frame(self.tabs, padding=6)
        self.review_tab = ttk.Frame(self.tabs, padding=6)
        self.replace_tab = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(self.preview_tab, text="Output preview ✅")
        self.tabs.add(self.replace_tab, text="Existing output (0)")
        self.tabs.add(self.review_tab, text="Review needed (0)")
        self.tabs.pack(fill="both", expand=True, padx=10, pady=4)
        cols = ("source", "destination", "reason", "size", "operation", "decision", "warning")
        headings = ("Original path", "Output destination", "Classification reason", "Size", "Operation", "Decision", "Warnings")
        widths = (230, 215, 175, 75, 105, 95, 160)
        self.table = ttk.Treeview(self.preview_tab, columns=cols, show="headings", selectmode="extended", height=7)
        self.review_table = ttk.Treeview(self.review_tab, columns=cols, show="headings", selectmode="extended", height=7)
        for tree in (self.table, self.review_table):
            for col, title, width in zip(cols, headings, widths):
                tree.heading(col, text=title); tree.column(col, width=width, anchor="w")
            tree.pack(fill="both", expand=True)
        existing_frame = ttk.Frame(self.replace_tab)
        existing_frame.pack(fill="both", expand=True)
        self.replace_table = ttk.Treeview(existing_frame,
            columns=("existing", "incoming", "old_size", "new_size", "status"),
            show="headings", selectmode="extended", height=7)
        for col, title, width in zip(
            ("existing", "incoming", "old_size", "new_size", "status"),
            ("Existing output file", "Incoming file", "Existing size", "Incoming size", "Decision"),
            (310, 310, 100, 100, 200)):
            self.replace_table.heading(col, text=title); self.replace_table.column(col, width=width, anchor="w")
        existing_y = ttk.Scrollbar(existing_frame, orient="vertical", command=self.replace_table.yview)
        existing_x = ttk.Scrollbar(existing_frame, orient="horizontal", command=self.replace_table.xview)
        self.replace_table.configure(yscrollcommand=existing_y.set, xscrollcommand=existing_x.set)
        self.replace_table.grid(row=0, column=0, sticky="nsew")
        existing_y.grid(row=0, column=1, sticky="ns")
        existing_x.grid(row=1, column=0, sticky="ew")
        existing_frame.rowconfigure(0, weight=1); existing_frame.columnconfigure(0, weight=1)
        self.existing_summary = tk.StringVar(value="Existing output matches: 0 files · 0 B")
        ttk.Label(self.replace_tab, textvariable=self.existing_summary, font=("Segoe UI", 10, "bold"), padding=(2, 6)).pack(anchor="w")
        ttk.Label(self.replace_tab, text="Matches are found inside the selected output destination. Copying them back is optional and never removes the originals.", padding=(2, 2)).pack(anchor="w")
        replace_actions = ttk.Frame(self.replace_tab); replace_actions.pack(fill="x", pady=(2, 0))
        ttk.Button(replace_actions, text="Select all existing conflicts", command=self.select_all_replace).pack(side="left", padx=2)
        ttk.Button(replace_actions, text="Copy selected existing files into their source folder", command=self.copy_existing_to_source).pack(side="left", padx=2)
        ttk.Button(replace_actions, text="Move selected existing files to source folder", command=lambda: self.copy_existing_to_source(move=True)).pack(side="left", padx=2)
        ttk.Button(replace_actions, text="Replace selected (backup for Undo)", command=lambda: self.decide_replace_selected("replace")).pack(side="left", padx=2)
        ttk.Button(replace_actions, text="Keep both (unique name)", command=lambda: self.decide_replace_selected("include")).pack(side="left", padx=2)
        ttk.Button(replace_actions, text="Exclude selected", command=lambda: self.decide_replace_selected("exclude")).pack(side="left", padx=2)
        preview_actions = ttk.Frame(self.preview_tab, padding=(0, 5))
        preview_actions.pack(fill="x")
        ttk.Label(preview_actions, text="Operation for selected file(s):").pack(side="left")
        self.selected_operation = ttk.Combobox(preview_actions, textvariable=self.operation_var,
            values=("Copy", "Move", "Copy, but delete source"), state="readonly", width=24)
        self.selected_operation.pack(side="left", padx=5)
        ttk.Button(preview_actions, text="Set selected operation", command=self.set_operation_selected).pack(side="left", padx=3)
        self.remove_button = ttk.Button(preview_actions, text="Remove selected from this run",
            command=self.remove_selected, state="disabled")
        self.remove_button.pack(side="left", padx=(10, 3))
        self.table.bind("<<TreeviewSelect>>", self._preview_selection_changed)
        self.review_table.bind("<<TreeviewSelect>>", self._review_selection_changed)
        review_selection = ttk.Frame(self.review_tab)
        review_selection.pack(fill="x", pady=(0, 2))
        ttk.Button(review_selection, text="Select all review files", command=self.select_all_review).pack(side="left")
        ttk.Button(review_selection, text="Select review files with no same-named output file", command=self.select_review_without_output_match).pack(side="left", padx=(6, 0))
        ttk.Label(review_selection, text="Choose files here, then pick an action below. Files needing a decision stay out of Apply until you decide.", padding=(6, 2), wraplength=430).pack(side="left", anchor="w")
        actions = ttk.Frame(self.review_tab); actions.pack(fill="x", pady=(2, 0))
        ttk.Button(actions, text="Keep both (unique name)", command=lambda: self.decide_selected("include")).pack(side="left", padx=2)
        self.review_replace_button = ttk.Button(actions, text="Replace existing (backup for Undo)", command=lambda: self.decide_selected("replace"), state="disabled")
        self.review_replace_button.pack(side="left", padx=2)
        ttk.Button(actions, text="Copy to Review Needed folder", command=lambda: self.decide_selected("review")).pack(side="left", padx=2)
        ttk.Button(actions, text="Exclude from this run", command=lambda: self.decide_selected("exclude")).pack(side="left", padx=2)
        ttk.Button(actions, text="Send all unresolved to Review Needed", command=lambda: self.decide_all("review")).pack(side="left", padx=(12, 2))
        ttk.Button(actions, text="Exclude all unresolved", command=lambda: self.decide_all("exclude")).pack(side="left", padx=2)
        op_box = ttk.Frame(self.root, padding=(10, 0)); op_box.pack(fill="x")
        ttk.Label(op_box, text="Operation for all scanned files:").pack(side="left")
        self.all_operation = ttk.Combobox(op_box, textvariable=self.operation_var,
            values=("Copy", "Move", "Copy, but delete source"), state="readonly", width=24)
        self.all_operation.pack(side="left", padx=5)
        ttk.Button(op_box, text="Set for all files", command=self.set_operation_all).pack(side="left")
        ttk.Label(op_box, text="You can minimize the app while a copy or verification runs.").pack(side="right")
        progress_row = ttk.Frame(self.root, padding=(10, 2))
        progress_row.pack(fill="x")
        self.progress_text = ttk.Label(progress_row, text="Copy progress will appear here", anchor="w")
        self.progress_text.pack(fill="x", pady=(0, 3))
        self.progress = ttk.Progressbar(progress_row, mode="determinate", maximum=100, value=0)
        self.progress.pack(fill="x", expand=True)
        self.progress_mode = "determinate"
        self.status_label = ttk.Label(self.root, textvariable=self.status, padding=(10, 4), wraplength=1000); self.status_label.pack(fill="x")

    def choose_destination(self):
        if self.operation_running: return
        path = filedialog.askdirectory(title="Choose organized files root")
        if path: self.destination.set(path)

    def _refresh_roots(self):
        self.root_list.delete(0, "end")
        for path in self.roots:
            key = str(path).casefold()
            size = self.root_sizes.get(key)
            size_text = "Calculating size…" if key in self.root_sizes and size is None else f"{size / (1024 ** 3):.2f} GB" if size is not None else "Size pending"
            self.root_list.insert("end", f"{path}  —  {size_text}")

    def _recalculate_root_sizes(self):
        self.size_scan_event.set()
        event = threading.Event()
        self.size_scan_event = event
        current_keys = {str(path).casefold() for path in self.roots}
        self.root_sizes = {key: value for key, value in self.root_sizes.items() if key in current_keys}
        for path in self.roots: self.root_sizes.setdefault(str(path).casefold(), None)
        self._refresh_roots()
        pending = [path for path in self.roots if self.root_sizes.get(str(path).casefold()) is None]
        if not pending: return

        def measure():
            for path in pending:
                if event.is_set(): return
                size = folder_size_bytes(path, event)
                if size is None: return
                key = str(path).casefold()
                try: self.root.after(0, lambda k=key, n=size, e=event: self._set_root_size(k, n, e))
                except tk.TclError: return
        threading.Thread(target=measure, daemon=True).start()

    def _set_root_size(self, key, size, event):
        if event is not self.size_scan_event or event.is_set(): return
        if key in {str(path).casefold() for path in self.roots}:
            self.root_sizes[key] = size
            self._refresh_roots()

    @staticmethod
    def _compact_path(path, max_length=64):
        value = str(path)
        if len(value) <= max_length: return value
        parts = Path(value).parts
        tail = "\\".join(parts[-3:])
        return "…\\" + tail if len(tail) < max_length - 2 else "…\\" + value[-(max_length - 2):]

    def _source_label(self, source):
        path = Path(source)
        for root in self.roots:
            try:
                relative = path.relative_to(root)
                short = Path(root.name) / relative
                return self._compact_path(short)
            except ValueError:
                pass
        return self._compact_path(path)

    def _destination_label(self, destination):
        path = Path(destination)
        try: path = path.relative_to(Path(self.destination.get()).expanduser())
        except ValueError: pass
        return self._compact_path(path)

    def open_output(self):
        path = Path(self.destination.get()).expanduser()
        if not path.is_dir():
            messagebox.showinfo("Output folder not created yet", f"The output will be written here after you apply changes:\n\n{path}")
            return
        try: os.startfile(path)
        except OSError as e: messagebox.showerror("Could not open output folder", str(e))

    def add_root(self):
        if self.operation_running: return
        try:
            paths = _select_multiple_folders(self.root.winfo_id())
        except Exception as exc:
            messagebox.showwarning("Multi-select unavailable", f"Could not open the multi-folder picker ({exc}). Choose one folder instead.")
            path = filedialog.askdirectory(title="Choose a folder to scan")
            paths = [path] if path else []
        added = []
        for path in paths:
            p = Path(path)
            if not any(str(existing).casefold() == str(p).casefold() for existing in self.roots):
                self.roots.append(p)
                added.append(p)
        if added:
            self._refresh_roots()
            self._recalculate_root_sizes()
            self._clear_results()
            self.status.set(f"Added {len(added)} scan location(s). Ctrl/Shift can select multiple folders in the picker.")
        elif paths:
            self.status.set("Those scan locations were already in the list.")

    def remove_roots(self):
        if self.operation_running: return
        selected = list(self.root_list.curselection())
        for i in reversed(selected): del self.roots[i]
        self._refresh_roots()
        self._recalculate_root_sizes()
        self._clear_results()
        self.status.set(f"{len(self.roots)} scan location(s) selected.")

    def _apply_operation(self, candidates, operation):
        if self.operation_running: return
        for candidate in candidates:
            candidate.operation = operation
            candidate.replace_existing = False
            candidate.replacement_target = ""
            if operation == "Exclude":
                candidate.decision = "exclude"
                candidate.reviewed = True
            elif candidate.decision == "exclude":
                candidate.decision = "pending" if candidate.category == "Review Needed" or candidate.warning else "include"
                candidate.reviewed = False
        self._refresh_proposals()
        self._refresh_tables()
        self.preview_ready = False
        self.status.set(f"Set {operation} for {len(candidates)} file(s). Preview the updated plan before applying.")

    def set_operation_all(self):
        if not self.candidates:
            messagebox.showinfo("Scan first", "Add a scan location and click Scan before choosing file operations.")
            return
        self._apply_operation(self.candidates, self.operation_var.get())

    def set_operation_selected(self):
        chosen = [self.candidates[int(item)] for item in self.table.selection()]
        if not chosen:
            messagebox.showinfo("Select files", "Select one or more rows in Output preview first.")
            return
        self._apply_operation(chosen, self.operation_var.get())

    def _preview_selection_changed(self, _event=None):
        self.remove_button.configure(state="normal" if self.table.selection() else "disabled")

    def remove_selected(self):
        if self.operation_running: return
        chosen = [self.candidates[int(item)] for item in self.table.selection()]
        for candidate in chosen:
            candidate.decision = "exclude"
            candidate.operation = "Exclude"
            candidate.replace_existing = False
            candidate.replacement_target = ""
            candidate.reviewed = True
        self._refresh_tables()
        self.remove_button.configure(state="disabled")
        self.preview_ready = False
        self.status.set(f"Removed {len(chosen)} selected file(s) from this run. Source and output files were not deleted.")

    def _clear_results(self):
        self.candidates = []
        self.preview_ready = False
        self._refresh_tables()

    def _log(self): return OperationLog(Path(self.destination.get()) / ".ai-file-organizer" / "operations.jsonl")

    def scan(self):
        if self.operation_running:
            self.status.set("Wait for the current file operation to finish or cancel it before scanning again.")
            return
        self.cancel_event.clear(); self._clear_results(); self.status.set("Scanning selected folders…")
        def work():
            errors = []
            last_update = [0.0]
            def progress(count, current):
                now = time.monotonic()
                if count == 1 or now - last_update[0] >= 0.35:
                    last_update[0] = now
                    self.root.after(0, lambda n=count, p=current: self.status.set(f"Scanning… {n:,} files found so far\nCurrent folder: {p}"))
            found = scan(self.roots, Path(self.destination.get()), self.cancel_event, errors.append, progress)
            self.root.after(0, lambda: self._show(found, errors))
        threading.Thread(target=work, daemon=True).start()

    def _show(self, found, errors):
        self.candidates = found
        self._refresh_proposals()
        self._refresh_tables()
        review_count = sum(c.decision == "pending" for c in found)
        self.tabs.tab(self.review_tab, text=f"Review needed ({review_count})")
        end_note = " Scan cancelled." if self.cancel_event.is_set() else ""
        self.status.set(f"Scan complete: {len(found):,} files found; {review_count} need a decision. No changes made.{end_note}" + (f" {len(errors)} inaccessible locations skipped." if errors else ""))
        self.tabs.select(self.review_tab if review_count else self.preview_tab)

    def _refresh_tables(self):
        if not self.existing_output_index:
            self._build_existing_output_index()
        self.replace_row_targets = {}
        for tree in (self.table, self.review_table, self.replace_table):
            for row in tree.get_children(): tree.delete(row)
        for index, c in enumerate(self.candidates):
            display_decision = "Exclude" if c.decision == "exclude" else "Copy" if c.decision == "include" else "Needs decision"
            display_decision = "Needs review" if c.decision == "pending" else display_decision
            values = (self._source_label(c.source), self._destination_label(c.destination), c.reason,
                      f"{c.size:,} bytes", c.operation, display_decision, c.warning)
            self.table.insert("", "end", iid=str(index), values=values)
            if c.decision == "pending": self.review_table.insert("", "end", iid=str(index), values=values)
            matches = self._existing_matches(c)
            for match_index, existing in enumerate(matches):
                row_id = f"{index}:{match_index}"
                self.replace_row_targets[row_id] = (index, existing)
                if c.replace_existing and Path(c.replacement_target or c.destination) == existing:
                    decision = "Replace (Undo backup)"
                elif c.decision == "exclude":
                    decision = "Excluded"
                elif c.decision == "pending":
                    decision = "Needs choice"
                else:
                    decision = "Keep both (unique name)"
                try: old_size = f"{existing.stat().st_size:,} bytes"
                except OSError: old_size = "Unavailable"
                self.replace_table.insert("", "end", iid=row_id, values=(
                    self._compact_path(existing), self._source_label(c.source), old_size,
                    f"{c.size:,} bytes", decision))
        count = sum(c.decision == "pending" for c in self.candidates)
        existing_count = len(self.replace_table.get_children(""))
        existing_bytes = 0
        existing_paths = set()
        for _candidate_index, existing in self.replace_row_targets.values():
            key = str(existing).casefold()
            if key in existing_paths: continue
            existing_paths.add(key)
            try: existing_bytes += existing.stat().st_size
            except OSError: pass
        self.existing_summary.set(f"Existing output matches: {len(existing_paths):,} unique files · {self._human_size(existing_bytes)} total")
        self.tabs.tab(self.review_tab, text=f"Review needed ({count})")
        self.tabs.tab(self.replace_tab, text=f"Existing output ({existing_count})")
        self.tabs.tab(self.preview_tab, text=f"Output preview {'🔴' if count else '✅'}")

    @staticmethod
    def _human_size(size):
        value = float(size)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB": return f"{value:.1f} {unit}"
            value /= 1024

    def copy_existing_to_source(self, move=False):
        """Copy or safely move selected output matches beside their original scan roots."""
        if self.operation_running: return
        selected = self.replace_table.selection()
        if not selected:
            messagebox.showinfo("Select existing files", "Select one or more rows in Existing output first. Use Select all existing conflicts to select every match.")
            return
        output = Path(self.destination.get()).expanduser()
        folder_label = f"Existing data in {output.name} - {output.parent.name}"
        plans = []
        seen = set()
        for row_id in selected:
            item = self.replace_row_targets.get(row_id)
            if not item: continue
            candidate_index, existing = item
            key = str(existing).casefold()
            if key in seen: continue
            seen.add(key)
            candidate = self.candidates[candidate_index]
            source = Path(candidate.source)
            roots = [root for root in self.roots if source == root or root in source.parents]
            if not roots:
                continue
            scan_root = max(roots, key=lambda root: len(root.parts))
            try: relative = source.relative_to(scan_root)
            except ValueError: continue
            # Keep the source's relative subfolder structure under the clearly named holding folder.
            target = scan_root / folder_label / relative.parent / existing.name
            try: size = existing.stat().st_size
            except OSError: continue
            plans.append(Candidate(str(existing), str(target), "Existing data", "Already present in selected output", size))
        if not plans:
            messagebox.showwarning("No usable matches", "The selected matches could not be linked to an active source folder. Refresh the scan and preview, then try again.")
            return
        total_bytes = sum(item.size for item in plans)
        action = "Move" if move else "Copy"
        move_note = " The output originals will be removed only after every new copy is verified and you confirm the cleanup." if move else " The output originals will remain in place."
        if not messagebox.askyesno(f"{action} existing output files to source",
            f"{action} {len(plans):,} already-existing file(s) ({self._human_size(total_bytes)}) into a folder named:\n\n{folder_label}\n\ninside the matching source folder(s)?\n\nExisting files will never be overwritten.{move_note}"):
            return
        free_ok, detail = preflight_destination_space(plans, Path(plans[0].destination).parent, reserve_bytes=0)
        if not free_ok:
            messagebox.showwarning("Storage check stopped the copy", detail)
            return
        self.operation_running = True
        self.cancel_event.clear()
        self.progress.configure(mode="determinate", value=0)
        self.progress_text.configure(text=f"Preparing existing-file copy · {len(plans):,} files · {self._human_size(total_bytes)}")
        self.status.set(f"Copying selected existing output files to the source-side holding folder. {'Move cleanup will require a separate confirmation.' if move else 'Output originals will be preserved.'}")
        def work():
            records, failures, cancelled = copy_batch_verified(plans, self._log(), self.cancel_event,
                lambda event: self.root.after(0, lambda e=event: self._update_progress(e)))
            def finish():
                preface = f"{len(records):,} existing file(s) copied and verified. "
                if cancelled: preface += "Copy was cancelled. Output originals remain. "
                if failures: preface += f"{len(failures):,} copy problem(s). Output originals remain. "
                if move and records and not failures and not cancelled:
                    if messagebox.askyesno("Confirm move cleanup", f"All {len(records):,} copies are verified. Remove the matching files from the output destination now?\n\nChanged or inaccessible files will be kept. Undo can restore removed files unless a newer file already exists at the old path."):
                        self._start_source_cleanup(records, "Move existing output files", preface, True)
                        return
                    preface += "Output originals remain because cleanup was not confirmed."
                self.operation_running = False
                self.status.set(preface)
                if failures: messagebox.showwarning("Some files could not be copied", "\n".join(failures[:8]))
                elif not cancelled: messagebox.showinfo("Copy completed", preface + f"\nSaved under {folder_label}.")
            self.root.after(0, finish)
        threading.Thread(target=work, daemon=True).start()

    def _existing_target(self, candidate):
        if candidate.operation == "Delete source": return None
        if candidate.replacement_target:
            target = Path(candidate.replacement_target)
            try:
                if target.is_file(): return target
            except OSError: pass
        output = Path(self.destination.get()).expanduser()
        target = output / candidate.category / Path(candidate.source).name
        try:
            if target.is_file(): return target
        except OSError: pass
        matches = self.existing_output_index.get(Path(candidate.source).name.casefold(), [])
        return matches[0] if len(matches) == 1 else None

    def _build_existing_output_index(self):
        output = Path(self.destination.get()).expanduser()
        self.existing_output_index = index_existing_files_by_name(output)
        self.existing_index_destination = str(output.resolve()) if output.exists() else str(output.absolute())

    def _existing_matches(self, candidate):
        if candidate.operation == "Delete source": return []
        exact = Path(self.destination.get()).expanduser() / candidate.category / Path(candidate.source).name
        try:
            if exact.is_file(): return [exact]
        except OSError: pass
        return self.existing_output_index.get(Path(candidate.source).name.casefold(), [])

    def _review_selection_changed(self, _event=None):
        chosen = [self.candidates[int(item)] for item in self.review_table.selection()]
        replace_allowed = bool(chosen) and all(len(self._existing_matches(c)) == 1 for c in chosen)
        self.review_replace_button.configure(state="normal" if replace_allowed else "disabled")

    def select_all_replace(self):
        rows = self.replace_table.get_children("")
        if rows:
            self.replace_table.selection_set(rows)
            self.replace_table.focus(rows[0])
            self.replace_table.see(rows[0])
            self.status.set(f"Selected all {len(rows):,} existing destination conflicts.")
        else:
            self.status.set("There are no existing destination files to replace.")

    def decide_replace_selected(self, action):
        if not self._existing_view_is_current():
            messagebox.showinfo("Refresh the preview", "The output destination changed. Click Preview Changes before deciding which existing file to replace.")
            return
        chosen = self.replace_table.selection()
        if not chosen:
            messagebox.showinfo("Select conflicts", "Select one or more files in the Existing output tab first.")
            return
        targets = {}
        candidate_ids = []
        for row_id in chosen:
            candidate_index, target = self.replace_row_targets[row_id]
            if action == "replace" and candidate_index in targets and targets[candidate_index] != target:
                messagebox.showwarning("Choose one existing match", "You selected multiple existing files for the same incoming file. Choose only one existing path to replace.")
                return
            targets.setdefault(candidate_index, target)
            if str(candidate_index) not in candidate_ids:
                candidate_ids.append(str(candidate_index))
        self._decide_candidate_ids(candidate_ids, action, targets)

    def decide_selected(self, action):
        chosen = self.review_table.selection()
        if not chosen:
            messagebox.showinfo("Select files", "Select one or more rows in the Review needed tab first.")
            return
        self._decide_candidate_ids(chosen, action)

    def _decide_candidate_ids(self, chosen, action, replacement_targets=None):
        if action == "replace" and not self._existing_view_is_current():
            messagebox.showinfo("Refresh the preview", "The output destination changed. Click Preview Changes before deciding which existing file to replace.")
            return
        replacement_targets = replacement_targets or {}
        output = Path(self.destination.get()).expanduser()
        selected_ids = {int(item) for item in chosen}
        used = {str(Path(c.destination)).casefold() for i, c in enumerate(self.candidates) if i not in selected_ids}
        for item in chosen:
            candidate = self.candidates[int(item)]
            if action == "exclude":
                candidate.decision = "exclude"
                candidate.replace_existing = False
                candidate.replacement_target = ""
            elif action == "replace":
                base = replacement_targets.get(int(item)) or self._existing_target(candidate)
                if base is None:
                    continue
                if str(base).casefold() in used:
                    candidate.operation = "Copy"
                    candidate.replace_existing = False
                    candidate.replacement_target = ""
                    candidate.destination = self._unique_proposal(base, used)
                    candidate.warning = "Another selected file uses this destination; kept both with a unique name"
                else:
                    candidate.operation = "Copy"
                    candidate.replace_existing = True
                    candidate.replacement_target = str(base)
                    candidate.destination = str(base)
                candidate.decision = "include"
            elif action == "review":
                candidate.operation = "Copy"
                candidate.category = "Review Needed"
                candidate.replace_existing = False
                candidate.replacement_target = ""
                candidate.destination = self._unique_proposal(output / candidate.category / Path(candidate.source).name, used)
                candidate.decision = "include"
            else:
                candidate.replace_existing = False
                candidate.replacement_target = ""
                candidate.decision = "include"
                base = output / ".ai-file-organizer" / "deleted" / candidate.category / Path(candidate.source).name if candidate.operation == "Delete source" else output / candidate.category / Path(candidate.source).name
                candidate.destination = self._unique_proposal(base, used)
            candidate.reviewed = True
            used.add(str(Path(candidate.destination)).casefold())
        self.preview_ready = False
        self._refresh_tables()
        self.status.set(f"Decision saved. {sum(c.decision == 'pending' for c in self.candidates)} file(s) still need a review decision.")

    def _existing_view_is_current(self):
        output = Path(self.destination.get()).expanduser()
        current = str(output.resolve()) if output.exists() else str(output.absolute())
        return self.existing_index_destination == current

    def select_all_review(self):
        """Select every row currently shown in the Review needed tab."""
        rows = self.review_table.get_children("")
        if not rows:
            self.status.set("There are no files in Review needed to select.")
            return
        self.review_table.selection_set(rows)
        self.review_table.focus(rows[0])
        self.review_table.see(rows[0])
        self.status.set(f"Selected all {len(rows):,} files in Review needed. Choose a review action below.")

    def select_review_without_output_match(self):
        """Select uncertain files whose names are not already present in output."""
        if self.operation_running: return
        if not self.candidates:
            messagebox.showinfo("Scan first", "Add a source folder and click Scan before selecting review files.")
            return
        if not self.preview_ready or not self._existing_view_is_current():
            messagebox.showinfo("Preview first", "Click Preview Changes after your last scan, review decision, or destination change. This refreshes the list of files already in the output before selecting unmatched files.")
            return
        no_match = set(indices_without_output_name_match(self.candidates, self.existing_output_index))
        rows = [row for row in self.review_table.get_children("") if int(row) in no_match]
        self.review_table.selection_remove(self.review_table.selection())
        if rows:
            self.review_table.selection_set(rows)
            self.review_table.focus(rows[0])
            self.review_table.see(rows[0])
            self.status.set(f"Selected {len(rows):,} review file(s) with no same-named file in the output destination. Choose an action below.")
        else:
            self.status.set("No review files without an output match were found.")
            messagebox.showinfo("No unmatched review files", "Every file waiting for review already has a same-named file in the output, or there are no review files. Check the Existing output tab for those matches.")

    def decide_all(self, action):
        pending = [c for c in self.candidates if c.decision == "pending"]
        if action == "exclude":
            for c in pending:
                c.decision = "exclude"
                c.reviewed = True
        else:
            output = Path(self.destination.get()).expanduser()
            used = {str(Path(c.destination)).casefold() for c in self.candidates if c.decision != "pending"}
            for c in pending:
                c.operation = "Copy"
                c.category = "Review Needed"
                c.replace_existing = False
                c.replacement_target = ""
                c.destination = self._unique_proposal(output / c.category / Path(c.source).name, used)
                c.decision = "include"
                c.reviewed = True
                used.add(str(Path(c.destination)).casefold())
        self.preview_ready = False
        self._refresh_tables()
        self.status.set(f"Decision saved for {len(pending)} file(s). Review the Output preview before applying.")

    @staticmethod
    def _unique_proposal(path, used):
        candidate = path
        index = 2
        while candidate.exists() or str(candidate).casefold() in used:
            candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
            index += 1
        return str(candidate)

    def analyze(self):
        if self.operation_running: return
        if not self.candidates:
            messagebox.showinfo("Scan first", "Choose scan locations and click Scan. The local analysis runs on the files found by that scan.")
            return
        for candidate in self.candidates:
            source = Path(candidate.source)
            context = source.parent
            for root in self.roots:
                try:
                    relative = source.relative_to(root)
                    context = Path(root.name) / relative.parent
                    break
                except ValueError:
                    continue
            category, reason = classify(source, context_path=context)
            candidate.category, candidate.reason = category, reason
        self._refresh_proposals()
        self._refresh_tables()
        self.preview_ready = False
        self.status.set(f"Local analysis complete for {len(self.candidates):,} files. No online or local AI model is configured; unmatched files and conflicts appear in Review needed. Review each decision before applying.")

    def _refresh_proposals(self):
        output = Path(self.destination.get()).expanduser()
        self._build_existing_output_index()
        counts = {}
        for c in self.candidates:
            if c.operation == "Delete source":
                base = output / ".ai-file-organizer" / "deleted" / c.category / Path(c.source).name
            else:
                base = output / c.category / Path(c.source).name
            key = str(base).casefold()
            counts[key] = counts.get(key, 0) + 1
        used = set()
        for c in self.candidates:
            planned = (output / ".ai-file-organizer" / "deleted" / c.category / Path(c.source).name
                       if c.operation == "Delete source" else output / c.category / Path(c.source).name)
            base = Path(c.replacement_target) if c.replace_existing and c.replacement_target else planned
            if c.replace_existing and not base.is_file():
                c.replace_existing = False
                c.replacement_target = ""
                base = planned
            key = str(planned).casefold()
            messages = []
            if counts[key] > 1: messages.append("Duplicate output filename; unique filename proposed")
            matches = self._existing_matches(c)
            if c.operation != "Delete source" and c.replace_existing and base.is_file():
                messages.append("Existing file will be backed up, then replaced")
            elif c.operation != "Delete source" and matches:
                messages.append("Same filename exists in output; choose replace or keep both")
            c.warning = "; ".join(messages)
            c.destination = str(base) if c.replace_existing else self._unique_proposal(planned, used)
            used.add(str(Path(c.destination)).casefold())
            if (c.category == "Review Needed" or c.warning) and not c.reviewed and c.decision == "include":
                c.decision = "pending"

    @staticmethod
    def _eta_text(seconds):
        if seconds is None: return "estimating ETA…"
        seconds = max(0, int(seconds))
        if seconds < 60: return f"about {seconds}s left"
        minutes, seconds = divmod(seconds, 60)
        if minutes < 60: return f"about {minutes}m {seconds}s left"
        hours, minutes = divmod(minutes, 60)
        return f"about {hours}h {minutes}m left"

    def _update_progress(self, event):
        stage = event["stage"]
        name = event.get("filename") or ""
        idx, total = event.get("index", 0), event.get("total_files", 0)
        eta = self._eta_text(event.get("eta_seconds"))
        eta_label = event.get("eta_phase", "ETA")
        if stage == "verify":
            if self.progress_mode != "indeterminate":
                self.progress.stop()
                self.progress.configure(mode="indeterminate", value=99)
                self.progress.start(12)
                self.progress_mode = "indeterminate"
            verify_pct = event.get("verify_percent", 0.0)
            self.progress_text.configure(text=f"Copy 99% · Verifying {verify_pct:.1f}% · {eta_label}: {eta} · {idx}/{total}: {name}")
        else:
            if self.progress_mode != "determinate":
                self.progress.stop()
                self.progress.configure(mode="determinate", value=99)
                self.progress_mode = "determinate"
            if stage == "copy":
                pct = event.get("copy_percent", 0.0)
                self.progress.configure(value=pct)
                self.progress_text.configure(text=f"Copying {pct:.1f}% · {eta_label}: {eta} · {idx}/{total}: {name}")
            elif stage == "publish":
                self.progress.configure(value=99)
                self.progress_text.configure(text=f"Publishing verified file {idx}/{total}: {name} · 99%")
            elif stage == "complete":
                self.progress.configure(value=100)
                self.progress_text.configure(text=f"Complete · {idx} files copied and verified")
            elif stage == "cancelled":
                self.progress.configure(value=event.get("copy_percent", 0.0))
                self.progress_text.configure(text=f"Cancelled · {event.get('published_count', 0)} verified file(s) published; temporary files discarded")
            elif stage == "error":
                self.progress.configure(value=99)
                self.progress_text.configure(text="Stopped with a problem · see status for details")
            elif stage == "cleanup":
                self.progress.configure(value=event.get("copy_percent", 0))
                self.progress_text.configure(text=f"Removing confirmed originals {idx}/{total}: {name} · {event.get('copy_percent', 0):.0f}%")

    def preview(self):
        if self.operation_running: return
        if not self.candidates: self.scan(); return
        self._build_existing_output_index()
        self._refresh_proposals()
        self._refresh_tables()
        self.tabs.select(self.preview_tab)
        self.preview_ready = True
        pending = sum(c.decision == "pending" for c in self.candidates)
        included = sum(c.decision == "include" for c in self.candidates)
        excluded = sum(c.decision == "exclude" for c in self.candidates)
        total_size = sum(c.size for c in self.candidates if c.decision == "include")
        self.status.set(f"Output preview: {included} files ready to copy ({total_size:,} bytes); {pending} awaiting a review decision; {excluded} excluded. Destination root: {self.destination.get()}")

    def apply(self):
        if self.operation_running: return
        if not self.candidates: messagebox.showinfo("Nothing to apply", "Scan files and review Preview Changes first."); return
        pending = sum(c.decision == "pending" for c in self.candidates)
        if pending:
            self.tabs.select(self.review_tab)
            messagebox.showinfo("Review required", f"{pending} file(s) still need a decision. Choose an action for each before applying.")
            return
        if not self.preview_ready:
            self.preview()
            messagebox.showinfo("Review output preview", "Check the Output preview tab, including destinations and excluded files. Then click Apply Changes to continue.")
            return
        selected = [c for c in self.candidates if c.decision == "include"]
        if not selected:
            messagebox.showinfo("Nothing selected", "All files are excluded from this operation.")
            return
        delete_files = [c for c in selected if c.operation == "Delete source"]
        move_files = [c for c in selected if c.operation in ("Move", "Copy, but delete source")]
        excluded = sum(c.decision == "exclude" for c in self.candidates)
        summary = (f"Copy: {sum(c.operation == 'Copy' for c in selected)}\n"
                   f"Move or Copy, but delete source (verify, then ask before cleanup): {len(move_files)}\n"
                   f"Delete source (verified Undo backup first): {len(delete_files)}\n"
                   f"Excluded: {excluded}\n\nOutput root: {self.destination.get()}")
        if not messagebox.askyesno("Confirm file operations", f"Proceed with the reviewed operations?\n\n{summary}"):
            return
        if delete_files and not messagebox.askyesno("Confirm source deletion", f"After verified backups are ready, remove these {len(delete_files)} source file(s)?\n\nUndo backups will be kept under:\n{Path(self.destination.get()) / '.ai-file-organizer' / 'deleted'}\n\nChanged or unreadable originals will be kept."):
            return
        enough_space, space_message = preflight_destination_space(selected, Path(self.destination.get()))
        if not enough_space:
            self.status.set("Stopped before copying: destination space could not be confirmed or is insufficient.")
            messagebox.showwarning("Storage check stopped the operation", space_message)
            return
        self.status.set(space_message)
        self.operation_running = True
        self.destination_entry.configure(state="readonly")
        self.cancel_event.clear(); self.status.set("Copying to staging, then verifying SHA-256…")
        self.progress.stop(); self.progress.configure(mode="determinate", value=0); self.progress_mode = "determinate"
        self.progress_text.configure(text="Starting copy…")
        def work():
            last_update = [0.0, ""]
            def progress_callback(event):
                now = time.monotonic()
                if event["stage"] != last_update[1] or now - last_update[0] >= 0.12:
                    last_update[:] = [now, event["stage"]]
                    self.root.after(0, lambda e=event: self._update_progress(e))
            records, failures, cancelled = copy_batch_verified(selected, self._log(), self.cancel_event, progress_callback)
            def finish():
                records_by_source = {r["source"]: r for r in records}
                cleanup_records = [records_by_source[str(c.source)] for c in delete_files + move_files if str(c.source) in records_by_source]
                preface = f"{len(records)} files copied and verified. "
                if failures: preface += f"{len(failures)} copy problem(s): {failures[0]}. "
                if cancelled: preface += "Copy stage cancelled. "
                delete_sources = [records_by_source[str(c.source)] for c in delete_files if str(c.source) in records_by_source]
                move_sources = [records_by_source[str(c.source)] for c in move_files if str(c.source) in records_by_source]
                confirmed_moves = []
                if move_sources and messagebox.askyesno("Confirm source cleanup", f"The {len(move_sources)} destination copies are verified. Remove these matching originals now?\n\nUndo can restore them unless a newer file already exists at the original path."):
                    confirmed_moves = move_sources
                cleanup_records = delete_sources + confirmed_moves
                operation_succeeded = not failures and not cancelled
                if cleanup_records:
                    label = "Delete and Move" if delete_sources and confirmed_moves else "Delete" if delete_sources else "Move"
                    self._start_source_cleanup(cleanup_records, label, preface, operation_succeeded)
                    return
                self.status.set(preface + "Originals remain unless you confirmed source cleanup.")
                self.operation_running = False
                self.destination_entry.configure(state="normal")
                if operation_succeeded:
                    messagebox.showinfo("Completed successfully", f"{len(records)} file(s) were copied and verified successfully.\n\nOriginals remain in their scan locations.")
            self.root.after(0, finish)
        threading.Thread(target=work, daemon=True).start()

    def _start_source_cleanup(self, records, label, preface, operation_succeeded):
        self.status.set(f"{preface}Removing confirmed source files after rechecking hashes…")
        self.progress.stop(); self.progress.configure(mode="determinate", value=0); self.progress_mode = "determinate"
        def work():
            def progress(index, total, name):
                event = {"stage": "cleanup", "index": index, "total_files": total,
                         "filename": name, "copy_percent": 100.0 * index / max(1, total)}
                self.root.after(0, lambda e=event: self._update_progress(e))
            removed, skipped = remove_sources_after_verified(records, self._log(), progress)
            def finish_cleanup():
                self.status.set(preface + f"{label}: removed {removed} unchanged source file(s). " +
                    (f"Kept {len(skipped)} source file(s): {skipped[0]}" if skipped else "Undo backup is available."))
                self.operation_running = False
                self.destination_entry.configure(state="normal")
                if operation_succeeded and not skipped:
                    messagebox.showinfo("Completed successfully", f"{preface}{label}: removed {removed} unchanged source file(s). Undo backups are available.")
                elif skipped:
                    messagebox.showwarning("Operation finished with files kept", f"The verified output is available. {len(skipped)} source file(s) were kept because they changed or could not be safely removed.")
            self.root.after(0, finish_cleanup)
        threading.Thread(target=work, daemon=True).start()

    def cancel(self):
        self.cancel_event.set(); self.status.set("Cancellation requested. Current temporary copy will be discarded safely.")

    def undo(self):
        if self.operation_running:
            messagebox.showinfo("Operation running", "Wait for the current operation to finish before undoing it.")
            return
        if not messagebox.askyesno("Undo copies", "Remove organizer-created copies whose current SHA-256 still matches the log? Newer or changed files will be kept."):
            return
        try: n = undo_last(self._log()); self.status.set(f"Undo complete: reversed {n} copies/moves or restored backups where originals were unchanged.")
        except Exception as e: messagebox.showerror("Undo failed", str(e))

def main():
    root = tk.Tk(); OrganizerApp(root); root.mainloop()

if __name__ == "__main__": main()
