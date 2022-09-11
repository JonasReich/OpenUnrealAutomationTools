"""
Source file browser for Unreal projects that allows file creation/deletion/move from templates and automatically updating the VS solution and Perforce.
Extension tool for VS users, because integrating this all in the solution explorer is a mess. This way it's accessible independent from IDE.
Does not rely on UCLASS metadata, so no automatic inheritance / header includes outside of the provided templates.

TODO:
- Add/Delete files
- Move/Rename files
- File templates

- Update project files button

- Add/remove module

- Perform some basic search for inheritance types to update module dependencies and header incldues?

- Add/remove plugin
- Activate/deactivate plugins
"""

import argparse
import enum
import glob
import os
import re
import shutil
import threading
import tkinter as tk
import tkinter.ttk as ttk
from locale import atoi
from pathlib import Path

from openunrealautomation.p4 import UnrealPerforce
from openunrealautomation.unrealengine import UnrealEngine

# TODO clean
_p4: UnrealPerforce = None


def get_p4() -> UnrealPerforce:
    global _p4
    return _p4


def set_p4(cwd) -> None:
    global _p4
    _p4 = UnrealPerforce(cwd=cwd, check=False)


class FileTreeIcons(enum.Enum):
    DIR = 0, "📁"
    FILE = 1, "📄"
    MISSING = 2, "💔"

    def __str__(self) -> str:
        return self.value[1]

    def get_by_path(path: str) -> str:
        if not os.path.exists(path):
            return str(FileTreeIcons.MISSING)
        if os.path.isdir(path):
            return PathType.get_from_path(path).get_icon()
        else:
            return SourceFileType.get_for_file(path).get_icon()


class PathType(enum.Enum):
    ROOT = 0, "rootdir", "#aaa", "📁"
    PLUGIN_ORG = 1, "pluginorg_dir", "#bbb", "📁"
    PLUGIN = 2, "plugin_dir", "#ccc", "📁"
    MODULE = 3, "module_dir", "#ddd", "📁"
    # The actual "Source" directory
    SOURCE = 4, "source_dir", "#eee", "📁"
    # Directories in the Private/Public folder (incl. "Public", "Private")
    SOURCE_SUB = 5, "source_sub_dir", "#fff", "📁"
    ANGELSCRIPT_ROOT = 6, "script_root", "#bbb", "📁"
    ANGELSCRIPT_SUB = 7, "script_sub", "#fff", "📁"
    FILE = 100, "file", "#ffd", "📄"

    @staticmethod
    def get_from_path(path: str, file_browser: "FileBrowser" = None) -> "PathType":
        if os.path.isfile(path):
            return PathType.FILE
        if (not file_browser is None) and path in file_browser.root_paths:
            return PathType.ROOT
        elif Path(path).name == "Source":
            return PathType.SOURCE
        elif "\\Source\\" in path:
            # module or source_sub
            if Path(path).parent.name == "Source":
                return PathType.MODULE
            else:
                return PathType.SOURCE_SUB
        elif "\\Plugins\\" in path:
            # plugin or plugin org dir
            if glob.glob(path + "\\*.uplugin"):
                return PathType.PLUGIN
            else:
                return PathType.PLUGIN_ORG
        elif Path(path).name == "Script":
            return PathType.ANGELSCRIPT_ROOT
        elif "\\Script\\" in path:
            return PathType.ANGELSCRIPT_SUB
        return PathType.ROOT

    def __int__(self) -> int:
        return self.value[0]

    def __str__(self) -> str:
        return self.value[1]

    def get_color(self) -> str:
        return self.value[2]

    def get_icon(self) -> str:
        return self.value[3]

    @staticmethod
    def configure_tags(tree: ttk.Treeview) -> None:
        for case in PathType:
            tree.tag_configure(str(case), background=case.get_color())


class SourceFileType(enum.Enum):
    CPP_HEADER = 0, "h", "📄"
    CPP_SOURCE = 1, "cpp", "📄"
    CPP_INL = 2, "inl", "📄"
    BUILD_CS = 10, "Build.cs", "⚙️"
    TARGET_CS = 11, "Target.cs", "⚙️"
    OTHER_CS = 12, "cs", "📄"
    PROJECT = 20, "uproject", "🎮"
    PLUGIN = 21, "uplugin", "🧩"
    ANGELSCRIPT = 30, "as", "📄"
    TEXT = 50, "txt", "📄"
    OTHER = TEXT

    def __str__(self) -> str:
        return self.value[1]

    @staticmethod
    def from_string(string: str) -> "SourceFileType":
        for file_type in SourceFileType:
            if file_type.value[1] == string:
                return file_type
        return SourceFileType.OTHER

    @staticmethod
    def get_for_file(path: str):
        for file_type in SourceFileType:
            if path.endswith(str(file_type)):
                return file_type
        return SourceFileType.OTHER

    def get_icon(self) -> str:
        return self.value[2]


def is_parent(tv: ttk.Treeview, suspected_parent, suspected_child) -> bool:
    for child in tv.get_children(suspected_parent):
        if child == suspected_child:
            return True
        elif is_parent(tv, child, suspected_child):
            return True
    return False


def _try_atoi(str) -> int:
    if not str is None:
        return atoi(str)
    else:
        return 0


class TtkGeometry():
    def __init__(self, width, height, x=0, y=0) -> None:
        self.width = width
        self.height = height
        self.x = x
        self.y = y

    def __str__(self) -> str:
        result = ""
        if self.width != 0 or self.height != 0:
            result += f"{self.width}x{self.height}"
        if not self.x is None:
            result += f"+{self.x}"
            if not self.y is None:
                result += f"+{self.y}"
        return result

    @staticmethod
    def from_string(string: str) -> "TtkGeometry":
        match = re.match(
            "(?P<width>\\d+)x(?P<height>\\d+)(\\+(?P<x>\\d+)(\\+(?P<y>\\d+))?)?", string)
        if match is None:
            return None
        return TtkGeometry(_try_atoi(match.group("width")),
                           _try_atoi(match.group("height")),
                           _try_atoi(match.group("x")),
                           _try_atoi(match.group("y")))


def ttk_grid_fill(widget: tk.Widget, column: int, row: int, columnspan=1, rowspan=1, sticky="nesw", column_weight: int = 1, row_weight: int = 1) -> None:
    padding = 3
    widget.grid(row=row,
                column=column,
                columnspan=columnspan,
                rowspan=rowspan,
                sticky=sticky,
                padx=padding,
                pady=padding)
    parent = widget.nametowidget(widget.winfo_parent())
    parent.columnconfigure(column, weight=column_weight)
    parent.rowconfigure(row, weight=row_weight)


class KeyBindings:
    """Key bindings and right click context menu"""

    def __init__(self, master, file_browser: "FileBrowser") -> None:
        # create a popup menu
        self.aMenu = tk.Menu(master, tearoff=0)
        self.aMenu.add_command(
            label="Delete",
            command=file_browser.delete_selected)
        self.aMenu.add_command(
            label="New File",
            command=file_browser.new_file)
        self.aMenu.add_command(
            label="New Folder",
            command=file_browser.new_folder)
        self.aMenu.add_command(
            label="Rename",
            command=file_browser.rename_selected)
        self.aMenu.add_command(
            label="Open",
            command=file_browser.open_explorer)

        # Global hotkeys
        master.bind("<Delete>", lambda event: file_browser.delete_selected())
        master.bind("<Control-d>",
                    lambda event: file_browser.delete_selected())
        master.bind("<Control-n>", lambda event: file_browser.new_file())
        master.bind("<Control-Shift-n>",
                    lambda event: file_browser.new_folder())
        master.bind("<F2>", lambda event: file_browser.rename_selected())
        master.bind("<Control-r>", lambda event: file_browser.refresh_roots())
        master.bind("<Control-o>", lambda event: file_browser.open_explorer())

        # Right click only on tree
        file_browser.tree.bind("<Button-3>", self.popup)

    def popup(self, event) -> None:
        self.aMenu.post(event.x_root, event.y_root)


class Selection_DragDrop(object):
    def __init__(self, root: tk.Tk, file_browser: "FileBrowser") -> None:
        self.file_browser = file_browser
        self.tree = file_browser.tree
        self.tree.bind("<ButtonPress-1>", self.bDown)
        self.tree.bind("<ButtonRelease-1>", self.bUp, add='+')
        self.tree.bind("<B1-Motion>", self.bMove, add='+')
        self.tree.bind("<Control-ButtonPress-1>", self.bDown_Control, add='+')
        self.tree.bind("<Control-ButtonRelease-1>", self.bUp_Control, add='+')
        self.moveto_row = None
        self.tooltip = None
        self.tooltip_label = None
        self.ctrl_down = False
        pass

    def is_movable(self, node) -> bool:
        node_path = self.file_browser.get_node_path(node)
        if node_path is None:
            return False
        # Only allow moving files and folders inside the source folders
        if os.path.isfile(node_path):
            file_type = SourceFileType.get_for_file(node_path)
            immovable_file_types = (
                SourceFileType.PLUGIN,
                SourceFileType.PROJECT
            )
            return file_type not in immovable_file_types
        path_type = PathType.get_from_path(node_path, self.file_browser)
        if path_type == PathType.SOURCE_SUB or path_type == PathType.MODULE:
            return True
        return False

    def is_multiselectable(self, node) -> bool:
        node_path = self.file_browser.get_node_path(node)
        if node_path is None:
            return

        # only allow files from the same folder if you want to add it to the multi-selection
        selection = self.tree.selection()
        if len(selection) > 0 and not Path(node_path).parent == Path(self.file_browser.get_node_path(selection[0])).parent:
            return False
        return True

    def bDown_Control(self, event) -> None:
        tv: ttk.Treeview = event.widget
        row = tv.identify_row(event.y)
        if self.is_multiselectable(row):
            tv.selection_add(row)
        else:
            tv.selection_set(row)
        self.ctrl_down = True

    def bDown(self, event) -> None:
        tv: ttk.Treeview = event.widget
        row = tv.identify_row(event.y)
        if row is None:
            return
        tv.selection_set(row)

    def bUp(self, event) -> None:
        tv: ttk.Treeview = event.widget
        if not self.tooltip is None:
            self.tooltip.destroy()
            self.tooltip = None
            self.tooltip_label = None

        if self.moveto_row is None:
            return
        self._try_move(tv)
        self.moveto_row = None

    def _try_move(self, tv) -> None:
        selection = list(tv.selection())
        if len(selection) == 0 \
                or self.moveto_row in selection \
                or self.moveto_row is None \
                or self.moveto_row not in self.file_browser.paths_by_node:
            return

        for item in selection:
            if not self.is_movable(item):
                return

        # Use parent directory for files
        path = self.file_browser.paths_by_node[self.moveto_row]
        moveto_row = self.moveto_row if os.path.isdir(
            path) else self.tree.parent(self.moveto_row)

        # prevent moving parent into child
        for node in selection:
            if is_parent(tv, node, moveto_row):
                print("Prevented moving into child node")
                return

        moveto_idx = tv.index(moveto_row)
        selection.sort(key=lambda item: self.tree.item(item)[
                       "text"], reverse=moveto_idx < tv.index(selection[0]))
        for node in selection:
            move_src = self.file_browser.get_node_path(node)
            moveto_dir = self.file_browser.get_node_path(moveto_row)
            if moveto_dir in self.file_browser.root_paths:
                return

            moveto = os.path.normpath(os.path.join(
                moveto_dir, Path(move_src).name))

            # Update mappings
            self.file_browser.nodes_by_path.pop(move_src)
            self.file_browser.paths_by_node[node] = moveto
            self.file_browser.nodes_by_path[moveto] = node

            # Move node
            tv.move(node, moveto_row, moveto_idx)

            # Move file
            shutil.move(move_src, moveto)
            get_p4().reconcile(move_src)
            get_p4().reconcile(moveto)

    def bUp_Control(self, event) -> None:
        self.ctrl_down = False
        self.bUp(event)

    def bMove(self, event) -> None:
        tv: ttk.Treeview = event.widget
        self.moveto_row = tv.identify_row(event.y)

        selection = tv.selection()
        immovable_item = next(
            (item for item in selection if self.is_movable(item) == False), None)

        if immovable_item is None:
            text = Path(self.file_browser.get_node_path(selection[0])).name if len(
                selection) == 1 else f"{len(selection)} items"
        else:
            text = f"🚫 can't move {Path(self.file_browser.get_node_path(immovable_item)).name} 🚫"

        geometry_str = str(TtkGeometry(0, 0, event.x_root+15, event.y_root+10))
        if self.tooltip is None:
            self.tooltip = tk.Toplevel()
            self.tooltip.overrideredirect(True)
            self.tooltip.geometry(geometry_str)
            self.tooltip_label = tk.Label(self.tooltip, text=text)
            self.tooltip_label.pack()
        else:
            self.tooltip_label.config(text=text)
            self.tooltip.geometry(geometry_str)


class Popup(tk.Toplevel):
    def __init__(self, root: tk.Tk, title: str, width: int, height: int, resizable: bool = True):
        super(Popup, self).__init__(root)
        self.wm_title(title)
        # This just tells the message to be on top of the root window.
        self.tkraise(root)

        root_geo = TtkGeometry.from_string(root.winfo_geometry())
        root_geo.x += int(root_geo.width / 2 - width / 2)
        root_geo.y += int(root_geo.height / 2 - height / 2)
        root_geo.width = width
        root_geo.height = height
        self.geometry(str(root_geo))
        self.resizable(resizable, resizable)


class NamePathElementDialog_Base(object):
    def __init__(self, root: tk.Tk, file_browser: "FileBrowser", dir: str, element_name: str, title: str, prompt: str) -> None:
        self.file_browser = file_browser
        self.dir = dir
        self.element_name = element_name

        self.popup = popup = Popup(
            root, title, width=300, height=90, resizable=False)
        frame = ttk.Frame(popup)
        ttk_grid_fill(frame, 0, 0, sticky="nwe")

        label = ttk.Label(frame, text=prompt)
        ttk_grid_fill(label, 0, 0, columnspan=2, sticky="ew")

        label = ttk.Label(frame, text="File Name")
        ttk_grid_fill(label, 0, 1, sticky="w")
        self.name_var = tk.StringVar(root, element_name)
        self.name_var.trace_add(
            "write", lambda name, index, mode, sv=self.name_var: self.name_changed())
        self.name_entry = ttk.Entry(frame, textvariable=self.name_var)
        self.name_entry.bind("<Return>", lambda event: self.submit())
        #self.name_entry.insert(0, element_name)
        self.name_entry.focus_set()
        ttk_grid_fill(self.name_entry, 1, 1)

        self.extension_point = ttk.Frame(frame)
        ttk_grid_fill(self.extension_point, 0, 2, columnspan=2)

        submit_button = ttk.Button(frame, text="OK", command=self.submit)
        ttk_grid_fill(submit_button, 0, 3, columnspan=2)

    def submit(self) -> None:
        # TODO validate names
        element_name = self.name_entry.get()
        full_path = os.path.join(self.dir, element_name)
        self.submit_impl(element_name, full_path)

        self.popup.destroy()

    def name_changed(self):
        # Implement in child classes if you want to react to name changes
        pass

    def submit_impl(self, element_name, full_path) -> None:
        raise NotImplementedError()


class NewFileDialog(NamePathElementDialog_Base):
    def __init__(self, root: tk.Tk, file_browser: "FileBrowser", dir: str) -> None:
        super(NewFileDialog, self).__init__(root, file_browser, dir,
                                            element_name="NewFile.txt",
                                            title="New File",
                                            prompt="Create new file...")

        preset_label = ttk.Label(self.extension_point,
                                 text="File Type / Preset")
        ttk_grid_fill(preset_label, 0, 0)
        options = [str(entry) for entry in SourceFileType]
        self.preset_var = tk.StringVar(root)
        self.preset_var.set(options[0])
        preset_opt = ttk.OptionMenu(
            self.extension_point, self.preset_var, None, *options, command=self.preset_changed)
        self.name_changed()
        ttk_grid_fill(preset_opt, 1, 0)
        geo = TtkGeometry.from_string(self.popup.winfo_geometry())
        geo.height += 20
        self.popup.geometry(str(geo))

    def apply_extension_setting(self):
        extension = self.preset_var.get()
        current_name = self.name_entry.get()
        if "." in current_name and not current_name.endswith(f".{extension}"):
            new_name = current_name.split(".")[0] + "." + extension
            self.name_var.set(new_name)

    def name_changed(self):
        current_name = self.name_var.get()
        extension = ".".join(current_name.split(".")[1:])
        # Automatically set the preset from the name:
        self.preset_var.set(SourceFileType.from_string(extension))

    def preset_changed(self, event):
        self.apply_extension_setting()

    def create_file(self, full_path):
        extension = self.preset_var.get()
        script_dir = os.path.dirname(os.path.realpath(__file__))
        template_path = os.path.join(
            script_dir, "sourcefilebrowser", f"template.{extension}")
        template_text = ""
        # TODO replace with template selection (multiple templates -> select from new popup / dropdown)
        if os.path.exists(template_path):
            with open(template_path, "r") as file:
                template_text = file.read()
                filename = str(os.path.basename(full_path)).split(".")[0]
                template_text = template_text.replace("%FILENAME%", filename)
                template_text = template_text.replace(
                    "%FILENAME%", filename)
                # TODO replace with copyright from project settings
                ue_config = self.file_browser.ue.environment.config()
                template_text = template_text.replace(
                    "%COPYRIGHT%",
                    ue_config.read(
                        "Game", "/Script/EngineSettings.GeneralProjectSettings", "CopyrightNotice").value
                )

                module_name = re.search("\\\\Source\\\\(?P<module>.+?)\\\\", full_path).group("module")
                template_text = template_text.replace("%API_MACRO%", f"{module_name.upper()}_API")

        with open(full_path, "w") as file:
            file.write(template_text)
            pass

    def submit_impl(self, filename, full_path) -> None:
        if not os.path.exists(full_path):
            self.create_file(full_path)
            get_p4().add(full_path)
            # create node
            parent_node = self.file_browser.nodes_by_path[self.dir]
            self.file_browser.insert_node(parent_node, filename, full_path)


class NewFolderDialog(NamePathElementDialog_Base):
    def __init__(self, root: tk.Tk, file_browser: "FileBrowser", dir: str) -> None:
        super(NewFolderDialog, self).__init__(root, file_browser, dir,
                                              element_name="NewFolder",
                                              title="New Folder",
                                              prompt="Create new folder...")

    def submit_impl(self, folder_name, full_path) -> None:
        if not os.path.exists(full_path):
            os.makedirs(full_path)
            # create node
            parent_node = self.file_browser.nodes_by_path[self.dir]
            self.file_browser.insert_node(parent_node, folder_name, full_path)


class RenamePathElementDialog(NamePathElementDialog_Base):
    old_path: str = ""

    def __init__(self, root: tk.Tk, file_browser: "FileBrowser", dir: str, element_name: str) -> None:
        self.old_path = os.path.join(dir, element_name)
        super(RenamePathElementDialog, self).__init__(root, file_browser, dir,
                                                      element_name=element_name,
                                                      title="Rename",
                                                      prompt="Rename file/directory...")

    def submit_impl(self, filename, full_path) -> None:
        # Update file on disk
        get_p4().edit(self.old_path)
        os.rename(self.old_path, full_path)
        get_p4().reconcile(self.old_path)
        get_p4().reconcile(full_path)

        # Update node
        node = self.file_browser.nodes_by_path.pop(self.old_path)
        self.file_browser.register_node(full_path, node)
        self.file_browser.tree.item(node, text=filename)


class FileBrowser(object):
    def __init__(self, root: tk.Tk, ue: UnrealEngine) -> None:
        self.paths_by_node = dict()
        self.root_paths = set()
        self.nodes_by_path = dict()

        self.root = root
        self.ue = ue

        self.frame = frame = tk.Frame(root)

        self.tree = ttk.Treeview(frame, selectmode="none")
        ysb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(frame, orient="horizontal",
                            command=self.tree.xview)
        self.tree.configure(yscroll=ysb.set, xscroll=xsb.set)
        ttk_grid_fill(self.tree, 0, 0)
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")

        self.tree.bind("<<TreeviewOpen>>", self.open_node)

        refresh_button = ttk.Button(
            frame, text="Generate Project Files", command=self.async_generate_project_files)
        refresh_button.grid(row=1, column=0, sticky="nesw")

        self.key_binds = KeyBindings(root, self)
        self.drag_drop = Selection_DragDrop(root, self)

        PathType.configure_tags(self.tree)

    def async_generate_project_files(self):
        threading.Thread(target=self.ue.generate_project_files,
                         kwargs={"extra_shell": True}).start()

    def destroy(self) -> None:
        self.frame.destroy()

    def register_node(self, path, node) -> None:
        # TODO HACK
        #path_as_src_path = os.path.normpath(os.path.join(path, "Source"))
        # if os.path.exists(path_as_src_path):
        #    path = path_as_src_path
        self.nodes_by_path[path] = node
        self.paths_by_node[node] = path

    def get_node_path(self, node) -> str:
        return self.paths_by_node.get(node, None)

    def insert_node(self, parent, text, abspath) -> str:
        path_type = PathType.get_from_path(abspath, self)
        tags = (str(path_type),)
        node = self.tree.insert(
            parent, "end", text=f"{FileTreeIcons.get_by_path(abspath)} {text}", open=False, tags=tags)
        self.register_node(abspath, node)
        if os.path.isdir(abspath):
            # insert an empty dummy node so graph shows the expand icon
            self.tree.insert(node, "end")
        return node

    def refresh_node_children(self, node) -> None:
        abspath = self.get_node_path(node)
        children = self.tree.get_children(node)
        for child in children:
            self.tree.delete(child)
        self.insert_node_path(abspath, node)

    def delete_selected(self) -> None:
        for node in self.tree.selection():
            parent = self.tree.parent(node)
            if not parent:
                print("Root elements cannot be deleted")
                return
            abspath = self.get_node_path(node)
            if abspath:
                get_p4().edit(abspath)
                if os.path.isdir(abspath):
                    shutil.rmtree(abspath)
                else:
                    os.remove(abspath)
                get_p4().reconcile(abspath)
                self.refresh_node_children(parent)

    def new_file(self) -> None:
        path = self.get_node_path(self.tree.focus())
        if os.path.isfile(path):
            path = str(Path(path).parent)
        NewFileDialog(self.root, self, path)

    def new_folder(self) -> None:
        path = self.get_node_path(self.tree.focus())
        if os.path.isfile(path):
            path = str(Path(path).parent)
        NewFolderDialog(self.root, self, path)

    def rename_selected(self) -> None:
        path = Path(self.get_node_path(self.tree.focus()))
        RenamePathElementDialog(
            self.root, self, dir=path.parent, element_name=path.name)

    def open_node(self, event) -> None:
        # This implements open / double-click, so use focus instead of selection -> maybe change?
        node = self.tree.focus()
        path = self.get_node_path(node)
        if path and os.path.isdir(path):
            # Clear and refresh children for folders
            self.refresh_node_children(node)

    def open_explorer(self) -> None:
        for node in self.tree.selection():
            os.startfile(self.get_node_path(node))

    def insert_node_path(self, path, parent_node) -> None:
        abspath = os.path.abspath(path)
        for element in os.listdir(abspath):
            nested_abspath = os.path.normpath(os.path.join(abspath, element))
            if element == "Source":
                # Skip the Source folder itself -> recurse
                self.insert_node_path(nested_abspath, parent_node)
            elif (
                # Add paths that are inside Source folders
                "\\Source" in nested_abspath or
                # Add folders that contain Source folders -> HACK
                len(glob.glob(f"{nested_abspath}\\Source\\")) > 0 or
                # Add uplugin files
                element.endswith("uplugin") or
                # Angelscript script support
                element == "Script" or "\\Script" in nested_abspath
            ):
                self.insert_node(parent_node, element, nested_abspath)

    def set_heading(self, heading) -> None:
        self.tree.heading("#0", text=heading, anchor="w")

    def insert_root(self, root) -> None:
        normpath = os.path.normpath(root)
        self.add_root_node(normpath)

    def refresh_roots(self) -> None:
        for path in self.root_paths:
            node = self.nodes_by_path[path]
            # Easy way out: Just collapse all -> Opening will refresh automatically
            # self.refresh_node_children(node)
            self.tree.item(node, open=False)

    def add_root_node(self, normpath) -> None:
        self.root_paths.add(normpath)
        root_node_name = ""
        if os.path.exists(normpath):
            node = self.insert_node(
                root_node_name, Path(normpath).name, normpath)
        else:
            node = self.tree.insert(
                "", "end",  text=f"{FileTreeIcons.MISSING} {normpath}", open=False)
        if not (node is None):
            self.register_node(normpath, node)


class App():
    rootdir: str = ""
    file_browser: FileBrowser = None

    def __init__(self, root) -> None:
        self.rootdir = os.path.abspath(root)
        print("rootdir ctor", self.rootdir)

        self.tkroot = self.create_tkroot(800, 500)

        rootdir_label = ttk.Label(self.tkroot, text="Project Root")
        ttk_grid_fill(rootdir_label, 0, 0, column_weight=0, row_weight=0)

        self.root_entry = ttk.Entry(self.tkroot, textvariable=self.rootdir)
        self.root_entry.insert(0, self.rootdir)
        ttk_grid_fill(self.root_entry, 1, 0, sticky="new", row_weight=0)
        self.root_entry.focus_set()
        self.root_entry.bind("<Return>", lambda event: self.init_browser())

        self.init_browser()

    @staticmethod
    def create_tkroot(sizex, sizey) -> tk.Tk:
        root = tk.Tk()
        root.geometry(str(TtkGeometry(sizex, sizey)))
        root.resizable(True, True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=0)
        root.rowconfigure(1, weight=1)

        # Fix for tag rows not working
        # https://stackoverflow.com/a/67846091/7486318
        style = ttk.Style(root)
        aktualTheme = style.theme_use()
        style.theme_create("dummy", parent=aktualTheme)
        style.theme_use("dummy")
        # make sure the selected items still show up properly. Otherwise only the tag colors show up.
        style.map('Treeview', background=[("selected", "#aaf")])

        return root

    def init_browser(self) -> None:
        entry_str = self.root_entry.get()
        if entry_str != "":
            self.rootdir = self.root_entry.get()

        set_p4(self.rootdir)
        print("root", self.rootdir)
        ue = UnrealEngine.create_from_parent_tree(self.rootdir)

        if not self.file_browser is None:
            self.file_browser.destroy()

        self.file_browser = FileBrowser(self.tkroot, ue)
        self.file_browser.set_heading(ue.environment.project_name)
        root_dir = ue.environment.project_root
        print("root_dir", root_dir)
        self.file_browser.insert_root(f"{root_dir}\\Source\\")
        self.file_browser.insert_root(f"{root_dir}\\Plugins\\")
        if os.path.exists(f"{root_dir}\\Script\\"):
            self.file_browser.insert_root(f"{root_dir}\\Script\\")
        self.file_browser.insert_root(ue.environment.project_file.file_path)
        self.tkroot.title(
            f"openunrealautomation Source Browser - {ue.environment.project_name}")

        ttk_grid_fill(self.file_browser.frame, 0, 1,
                      columnspan=2, column_weight=0)

    def mainloop(self):
        self.tkroot.mainloop()


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument("--root", default="./")
    args = argparser.parse_args()

    app = App(root=args.root)
    app.mainloop()
