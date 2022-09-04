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

import os
import shutil
import tkinter as tk
import tkinter.ttk as ttk

from typing import Tuple
from pathlib import Path

import enum
import glob

from openunrealautomation.unrealengine import UnrealEngine


class FileTreeIcons(enum.Enum):
    DIR = 0, "📁"
    FILE = 1, "📄"
    MISSING = 2, "💔"

    def __str__(self):
        return self.value[1]

    def get_by_path(path: str) -> str:
        return str(FileTreeIcons.DIR if os.path.isdir(path) else FileTreeIcons.FILE)


class PathType(enum.Enum):
    ROOT = 0, "rootdir", "#aaa"
    PLUGIN_ORG = 1, "pluginorg_dir", "#bbb"
    PLUGIN = 2, "plugin_dir", "#ccc"
    MODULE = 3, "module_dir", "#ddd"
    # The actual "Source" directory
    SOURCE = 4, "source_dir", "#eee"
    # Directories in the Private/Public folder (incl. "Public", "Private")
    SOURCE_SUB = 5, "source_sub_dir", "#fff"
    FILE = 6, "file", "#ffd"

    @staticmethod
    def get_from_path(path: str, file_browser: "FileBrowser") -> "PathType":
        if os.path.isfile(path):
            return PathType.FILE
        if path in file_browser.root_paths:
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
        assert False, "This point must never be reached"

    def __int__(self) -> int:
        return self.value[0]

    def __str__(self) -> str:
        return self.value[1]

    def get_color(self) -> str:
        return self.value[2]

    @staticmethod
    def configure_tags(tree: ttk.Treeview):
        for case in PathType:
            tree.tag_configure(str(case), background=case.get_color())


def is_parent(tv: ttk.Treeview, suspected_parent, suspected_child):
    for child in tv.get_children(suspected_parent):
        if child == suspected_child:
            return True
        elif is_parent(tv, child, suspected_child):
            return True
    return False


class KeyBindings:
    def __init__(self, master, file_browser: "FileBrowser"):
        # create a popup menu
        self.aMenu = tk.Menu(master, tearoff=0)
        self.aMenu.add_command(
            label="Delete",
            command=file_browser.delete_selected)
        self.aMenu.add_command(
            label="New",
            command=file_browser.new_file)
        self.aMenu.add_command(
            label="Open",
            command=file_browser.open_explorer)

        # Global hotkeys
        master.bind("<Delete>", lambda event: file_browser.delete_selected())
        master.bind("<Control-d>",
                    lambda event: file_browser.delete_selected())
        master.bind("<Control-n>", lambda event: file_browser.new_file())
        master.bind("<Control-r>", lambda event: file_browser.refresh_roots())
        master.bind("<Control-o>", lambda event: file_browser.open_explorer())

        # Right click only on tree
        file_browser.tree.bind("<Button-3>", self.popup)

    def popup(self, event):
        self.aMenu.post(event.x_root, event.y_root)


class Selection_DragDrop(object):
    def __init__(self, root: tk.Tk, file_browser: "FileBrowser"):
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
            return True
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

    def bDown_Control(self, event):
        tv: ttk.Treeview = event.widget
        row = tv.identify_row(event.y)
        if self.is_multiselectable(row):
            tv.selection_add(row)
        else:
            tv.selection_set(row)
        self.ctrl_down = True

    def bDown(self, event):
        tv: ttk.Treeview = event.widget
        row = tv.identify_row(event.y)
        if row is None:
            return
        tv.selection_set(row)

    def bUp(self, event):
        tv: ttk.Treeview = event.widget
        if not self.tooltip is None:
            self.tooltip.destroy()
            self.tooltip = None
            self.tooltip_label = None

        if self.moveto_row is None:
            return
        self._try_move(tv)
        self.moveto_row = None

    def _try_move(self, tv):
        selection = list(tv.selection())
        if len(selection) == 0 or self.moveto_row in selection \
                or self.moveto_row is None or self.moveto_row not in file_browser.paths_by_node:
            return

        for item in selection:
            if not self.is_movable(item):
                return

        # Use parent directory for files
        path = file_browser.paths_by_node[self.moveto_row]
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

    def bUp_Control(self, event):
        self.ctrl_down = False
        self.bUp(event)

    def bMove(self, event):
        tv: ttk.Treeview = event.widget
        self.moveto_row = tv.identify_row(event.y)

        selection = tv.selection()
        text = self.file_browser.paths_by_node[selection[0]] if len(
            selection) == 1 else f"{len(selection)} items"
        geometry_str = f'+{event.x_root+15}+{event.y_root+10}'
        if self.tooltip is None:
            self.tooltip = tk.Toplevel()
            self.tooltip.overrideredirect(True)
            self.tooltip.geometry(geometry_str)
            self.tooltip_label = tk.Label(self.tooltip, text=text)
            self.tooltip_label.pack()
        else:
            self.tooltip_label.config(text=text)
            self.tooltip.geometry(geometry_str)


def ttk_grid_fill(widget: tk.Widget, column: int, row: int):
    widget.grid(row=row, column=column, sticky="nesw")
    widget.columnconfigure(column, weight=1)
    widget.rowconfigure(row, weight=1)


class FileBrowser(object):
    def __init__(self, root: tk.Tk, ue: UnrealEngine):
        self.paths_by_node = dict()
        self.root_paths = set()
        self.nodes_by_path = dict()

        # Fix for tag rows not working
        # https://stackoverflow.com/a/67846091/7486318
        style = ttk.Style(root)
        aktualTheme = style.theme_use()
        style.theme_create("dummy", parent=aktualTheme)
        style.theme_use("dummy")
        # make sure the selected items still show up properly. Otherwise only the tag colors show up.
        style.map('Treeview', background=[("selected", "#aaf")])

        frame = tk.Frame(root)
        ttk_grid_fill(frame, 0, 0)

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
            frame, text="Generate Project Files", command=ue.generate_project_files)
        refresh_button.grid(row=1, column=0, sticky="nesw")

        self.key_binds = KeyBindings(root, self)
        self.drag_drop = Selection_DragDrop(root, self)

        PathType.configure_tags(self.tree)

    def register_node(self, path, node):
        # TODO HACK
        path_as_src_path = os.path.normpath(os.path.join(path, "Source"))
        if os.path.exists(path_as_src_path):
            path = path_as_src_path
        self.nodes_by_path[path] = node
        self.paths_by_node[node] = path

    def get_node_path(self, node) -> str:
        return self.paths_by_node.get(node, None)

    def insert_node(self, parent, text, abspath):
        path_type = PathType.get_from_path(abspath, self)
        tags = (str(path_type),)
        node = self.tree.insert(
            parent, "end", text=f"{FileTreeIcons.get_by_path(abspath)} {text}", open=False, tags=tags)
        self.register_node(abspath, node)
        if os.path.isdir(abspath):
            # insert an empty dummy node so graph shows the expand icon
            self.tree.insert(node, "end")
        return node

    def refresh_node_children(self, node):
        abspath = self.get_node_path(node)
        children = self.tree.get_children(node)
        for child in children:
            self.tree.delete(child)
        self.insert_node_path(abspath, node)

    def delete_selected(self):
        for node in self.tree.selection():
            parent = self.tree.parent(node)
            if not parent:
                print("Root elements cannot be deleted")
                return
            abspath = self.get_node_path(node)
            if abspath:
                if os.path.isdir(abspath):
                    shutil.rmtree(abspath)
                else:
                    os.remove(abspath)
                self.refresh_node_children(parent)

    def new_file(self):
        print("TODO: new file")

    def open_node(self, event):
        # This implements open / double-click, so use focus instead of selection -> maybe change?
        node = self.tree.focus()
        path = self.get_node_path(node)
        if path:
            if os.path.isfile(path):
                os.startfile(path)
                return

            # Clear and refresh children for folders
            self.refresh_node_children(node)

    def open_explorer(self):
        for node in self.tree.selection():
            os.startfile(self.get_node_path(node))

    def insert_node_path(self, path, parent_node):
        abspath = os.path.abspath(path)
        for element in os.listdir(abspath):
            nested_abspath = os.path.normpath(os.path.join(abspath, element))
            # Skip the Source folder itself -> recurse
            if element == "Source":
                self.insert_node_path(nested_abspath, parent_node)
            elif (
                # Add paths that are inside Source folders
                "\\Source" in nested_abspath or
                # Add folders that contain Source folders -> HACK
                len(glob.glob(f"{nested_abspath}\\Source\\")) > 0
            ):
                self.insert_node(parent_node, element, nested_abspath)

    def set_heading(self, heading):
        self.tree.heading("#0", text=heading, anchor="w")

    def insert_root(self, root):
        normpath = os.path.normpath(root)
        self.add_root_node(normpath)

    def refresh_roots(self):
        for path in self.root_paths:
            node = self.nodes_by_path[path]
            # Easy way out: Just collapse all -> Opening will refresh automatically
            # self.refresh_node_children(node)
            self.tree.item(node, open=False)

    def add_root_node(self, normpath):
        self.root_paths.add(normpath)
        root_node_name = ""
        if os.path.exists(normpath):
            node = self.insert_node(root_node_name, normpath, normpath)
        else:
            node = self.tree.insert(
                "", "end",  text=f"{FileTreeIcons.MISSING} {normpath}", open=False)
        if not (node is None):
            self.register_node(normpath, node)


def create_tkroot(sizex, sizey):
    root = tk.Tk()
    root.geometry(f"{sizex}x{sizey}")
    root.resizable(True, True)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    return root


if __name__ == "__main__":
    tkroot = create_tkroot(800, 500)

    ue = UnrealEngine.create_from_parent_tree("./")
    root_dir = ue.environment.project_root
    tkroot.title(
        f"openunrealautomation Source Browser - {ue.environment.project_name}")

    file_browser = FileBrowser(tkroot, ue)
    file_browser.set_heading(ue.environment.project_name)
    file_browser.insert_root(f"{root_dir}\\Source\\")
    file_browser.insert_root(f"{root_dir}\\Plugins\\")

    tkroot.mainloop()
