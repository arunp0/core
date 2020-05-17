import logging
import tkinter as tk
from enum import Enum
from functools import partial
from tkinter import ttk
from typing import TYPE_CHECKING, Callable

from PIL.ImageTk import PhotoImage

from core.api.grpc import core_pb2
from core.gui.dialogs.marker import MarkerDialog
from core.gui.dialogs.runtool import RunToolDialog
from core.gui.graph.enums import GraphMode
from core.gui.graph.shapeutils import ShapeType, is_marker
from core.gui.images import ImageEnum
from core.gui.nodeutils import NodeDraw, NodeUtils
from core.gui.task import ProgressTask
from core.gui.themes import Styles
from core.gui.tooltip import Tooltip

if TYPE_CHECKING:
    from core.gui.app import Application

TOOLBAR_SIZE = 32
PICKER_SIZE = 24


class NodeTypeEnum(Enum):
    NODE = 0
    NETWORK = 1
    OTHER = 2


def enable_buttons(frame: ttk.Frame, enabled: bool) -> None:
    state = tk.NORMAL if enabled else tk.DISABLED
    for child in frame.winfo_children():
        child.configure(state=state)


class PickerFrame(ttk.Frame):
    def __init__(self, app: "Application", button: ttk.Button) -> None:
        super().__init__(app)
        self.app = app
        self.button = button

    def create_button(self, label: str, image_enum: ImageEnum, func: Callable) -> None:
        bar_image = self.app.get_icon(image_enum, TOOLBAR_SIZE)
        image = self.app.get_icon(image_enum, PICKER_SIZE)
        self._create_button(label, image, bar_image, func)

    def create_custom_button(self, label: str, image_file: str, func: Callable) -> None:
        bar_image = self.app.get_custom_icon(image_file, TOOLBAR_SIZE)
        image = self.app.get_custom_icon(image_file, PICKER_SIZE)
        self._create_button(label, image, bar_image, func)

    def _create_button(
        self, label: str, image: PhotoImage, bar_image: PhotoImage, func: Callable
    ) -> None:
        button = ttk.Button(
            self, image=image, text=label, compound=tk.TOP, style=Styles.picker_button
        )
        button.image = image
        button.bind("<ButtonRelease-1>", lambda e: func(bar_image))
        button.grid(pady=1)

    def show(self) -> None:
        self.button.after(0, self._show)

    def _show(self) -> None:
        x = self.button.winfo_width() + 1
        y = self.button.winfo_rooty() - self.app.winfo_rooty() - 1
        self.place(x=x, y=y)
        self.app.bind_all("<ButtonRelease-1>", lambda e: self.destroy())
        self.wait_visibility()
        self.grab_set()
        self.wait_window()
        self.app.unbind_all("<ButtonRelease-1>")


class ButtonBar(ttk.Frame):
    def __init__(self, master: tk.Widget, app: "Application"):
        super().__init__(master)
        self.app = app
        self.radio_buttons = []

    def create_button(
        self, image_enum: ImageEnum, func: Callable, tooltip: str, radio: bool = False
    ) -> ttk.Button:
        image = self.app.get_icon(image_enum, TOOLBAR_SIZE)
        button = ttk.Button(self, image=image, command=func)
        button.image = image
        button.grid(sticky="ew")
        Tooltip(button, tooltip)
        if radio:
            self.radio_buttons.append(button)
        return button

    def select_radio(self, selected: ttk.Button) -> None:
        for button in self.radio_buttons:
            button.state(["!pressed"])
        selected.state(["pressed"])


class Toolbar(ttk.Frame):
    """
    Core toolbar class
    """

    def __init__(self, app: "Application") -> None:
        """
        Create a CoreToolbar instance
        """
        super().__init__(app)
        self.app = app

        # design buttons
        self.play_button = None
        self.select_button = None
        self.link_button = None
        self.node_button = None
        self.network_button = None
        self.annotation_button = None

        # runtime buttons
        self.runtime_select_button = None
        self.stop_button = None
        self.runtime_marker_button = None
        self.run_command_button = None

        # frames
        self.design_frame = None
        self.runtime_frame = None
        self.picker = None

        # dialog
        self.marker_tool = None

        # these variables help keep track of what images being drawn so that scaling
        # is possible since PhotoImage does not have resize method
        self.node_enum = None
        self.node_file = None
        self.network_enum = None
        self.annotation_enum = None

        # draw components
        self.draw()

    def draw(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.draw_design_frame()
        self.draw_runtime_frame()
        self.design_frame.tkraise()

    def draw_design_frame(self) -> None:
        self.design_frame = ButtonBar(self, self.app)
        self.design_frame.grid(row=0, column=0, sticky="nsew")
        self.design_frame.columnconfigure(0, weight=1)
        self.play_button = self.design_frame.create_button(
            ImageEnum.START, self.click_start, "Start Session"
        )
        self.select_button = self.design_frame.create_button(
            ImageEnum.SELECT, self.click_selection, "Selection Tool", radio=True
        )
        self.link_button = self.design_frame.create_button(
            ImageEnum.LINK, self.click_link, "Link Tool", radio=True
        )
        self.node_enum = ImageEnum.ROUTER
        self.node_button = self.design_frame.create_button(
            self.node_enum, self.draw_node_picker, "Container Nodes", radio=True
        )
        self.network_enum = ImageEnum.HUB
        self.network_button = self.design_frame.create_button(
            self.network_enum, self.draw_network_picker, "Link Layer Nodes", radio=True
        )
        self.annotation_enum = ImageEnum.MARKER
        self.annotation_button = self.design_frame.create_button(
            self.annotation_enum,
            self.draw_annotation_picker,
            "Annotation Tools",
            radio=True,
        )

    def draw_runtime_frame(self) -> None:
        self.runtime_frame = ButtonBar(self, self.app)
        self.runtime_frame.grid(row=0, column=0, sticky="nsew")
        self.runtime_frame.columnconfigure(0, weight=1)
        self.stop_button = self.runtime_frame.create_button(
            ImageEnum.STOP, self.click_stop, "Stop Session"
        )
        self.runtime_select_button = self.runtime_frame.create_button(
            ImageEnum.SELECT, self.click_runtime_selection, "Selection Tool", radio=True
        )
        self.runtime_marker_button = self.runtime_frame.create_button(
            ImageEnum.MARKER, self.click_marker_button, "Marker Tool", radio=True
        )
        self.run_command_button = self.runtime_frame.create_button(
            ImageEnum.RUN, self.click_run_button, "Run Tool"
        )

    def draw_node_picker(self) -> None:
        self.design_frame.select_radio(self.node_button)
        self.picker = PickerFrame(self.app, self.node_button)
        # draw default nodes
        for node_draw in NodeUtils.NODES:
            func = partial(
                self.update_button, self.node_button, node_draw, NodeTypeEnum.NODE
            )
            self.picker.create_button(node_draw.label, node_draw.image_enum, func)
        # draw custom nodes
        for name in sorted(self.app.core.custom_nodes):
            node_draw = self.app.core.custom_nodes[name]
            func = partial(
                self.update_button, self.node_button, node_draw, NodeTypeEnum.NODE
            )
            self.picker.create_custom_button(
                node_draw.label, node_draw.image_file, func
            )
        self.picker.show()

    def click_selection(self) -> None:
        self.design_frame.select_radio(self.select_button)
        self.app.canvas.mode = GraphMode.SELECT

    def click_runtime_selection(self) -> None:
        self.runtime_frame.select_radio(self.runtime_select_button)
        self.app.canvas.mode = GraphMode.SELECT

    def click_start(self) -> None:
        """
        Start session handler redraw buttons, send node and link messages to grpc
        server.
        """
        self.app.menubar.change_menubar_item_state(is_runtime=True)
        self.app.canvas.mode = GraphMode.SELECT
        enable_buttons(self.design_frame, enabled=False)
        task = ProgressTask(
            self.app, "Start", self.app.core.start_session, self.start_callback
        )
        task.start()

    def start_callback(self, response: core_pb2.StartSessionResponse) -> None:
        if response.result:
            self.set_runtime()
            self.app.core.set_metadata()
            self.app.core.show_mobility_players()
        else:
            enable_buttons(self.design_frame, enabled=True)
            message = "\n".join(response.exceptions)
            self.app.show_error("Start Session Error", message)

    def set_runtime(self) -> None:
        enable_buttons(self.runtime_frame, enabled=True)
        self.runtime_frame.tkraise()
        self.click_runtime_selection()

    def set_design(self) -> None:
        enable_buttons(self.design_frame, enabled=True)
        self.design_frame.tkraise()
        self.click_selection()

    def click_link(self) -> None:
        self.design_frame.select_radio(self.link_button)
        self.app.canvas.mode = GraphMode.EDGE

    def update_button(
        self,
        button: ttk.Button,
        node_draw: NodeDraw,
        type_enum: NodeTypeEnum,
        image: PhotoImage,
    ) -> None:
        logging.debug("update button(%s): %s", button, node_draw)
        button.configure(image=image)
        button.image = image
        self.app.canvas.mode = GraphMode.NODE
        self.app.canvas.node_draw = node_draw
        if type_enum == NodeTypeEnum.NODE:
            if node_draw.image_enum:
                self.node_enum = node_draw.image_enum
                self.node_file = None
            elif node_draw.image_file:
                self.node_file = node_draw.image_file
                self.node_enum = None
        elif type_enum == NodeTypeEnum.NETWORK:
            self.network_enum = node_draw.image_enum

    def draw_network_picker(self) -> None:
        """
        Draw the options for link-layer button.
        """
        self.design_frame.select_radio(self.network_button)
        self.picker = PickerFrame(self.app, self.network_button)
        for node_draw in NodeUtils.NETWORK_NODES:
            func = partial(
                self.update_button, self.network_button, node_draw, NodeTypeEnum.NETWORK
            )
            self.picker.create_button(node_draw.label, node_draw.image_enum, func)
        self.picker.show()

    def draw_annotation_picker(self) -> None:
        """
        Draw the options for marker button.
        """
        self.design_frame.select_radio(self.annotation_button)
        self.picker = PickerFrame(self.app, self.annotation_button)
        nodes = [
            (ImageEnum.MARKER, ShapeType.MARKER),
            (ImageEnum.OVAL, ShapeType.OVAL),
            (ImageEnum.RECTANGLE, ShapeType.RECTANGLE),
            (ImageEnum.TEXT, ShapeType.TEXT),
        ]
        for image_enum, shape_type in nodes:
            label = shape_type.value
            func = partial(self.update_annotation, shape_type, image_enum)
            self.picker.create_button(label, image_enum, func)
        self.picker.show()

    def create_observe_button(self) -> None:
        image = self.app.get_icon(ImageEnum.OBSERVE, TOOLBAR_SIZE)
        menu_button = ttk.Menubutton(
            self.runtime_frame, image=image, direction=tk.RIGHT
        )
        menu_button.grid(sticky="ew")
        menu = tk.Menu(menu_button, tearoff=0)
        menu_button["menu"] = menu
        menu.add_command(label="None")
        menu.add_command(label="processes")
        menu.add_command(label="ifconfig")
        menu.add_command(label="IPv4 routes")
        menu.add_command(label="IPv6 routes")
        menu.add_command(label="OSPFv2 neighbors")
        menu.add_command(label="OSPFv3 neighbors")
        menu.add_command(label="Listening sockets")
        menu.add_command(label="IPv4 MFC entries")
        menu.add_command(label="IPv6 MFC entries")
        menu.add_command(label="firewall rules")
        menu.add_command(label="IPSec policies")
        menu.add_command(label="docker logs")
        menu.add_command(label="OSPFv3 MDR level")
        menu.add_command(label="PIM neighbors")
        menu.add_command(label="Edit...")

    def click_stop(self) -> None:
        """
        redraw buttons on the toolbar, send node and link messages to grpc server
        """
        logging.info("clicked stop button")
        self.app.menubar.change_menubar_item_state(is_runtime=False)
        self.app.core.close_mobility_players()
        enable_buttons(self.runtime_frame, enabled=False)
        task = ProgressTask(
            self.app, "Stop", self.app.core.stop_session, self.stop_callback
        )
        task.start()

    def stop_callback(self, response: core_pb2.StopSessionResponse) -> None:
        self.set_design()
        self.app.canvas.stopped_session()

    def update_annotation(
        self, shape_type: ShapeType, image_enum: ImageEnum, image: PhotoImage
    ) -> None:
        logging.debug("clicked annotation")
        self.annotation_button.configure(image=image)
        self.annotation_button.image = image
        self.app.canvas.mode = GraphMode.ANNOTATION
        self.app.canvas.annotation_type = shape_type
        self.annotation_enum = image_enum
        if is_marker(shape_type):
            if self.marker_tool:
                self.marker_tool.destroy()
            self.marker_tool = MarkerDialog(self.app)
            self.marker_tool.show()

    def click_run_button(self) -> None:
        logging.debug("Click on RUN button")
        dialog = RunToolDialog(self.app)
        dialog.show()

    def click_marker_button(self) -> None:
        self.runtime_frame.select_radio(self.runtime_marker_button)
        self.app.canvas.mode = GraphMode.ANNOTATION
        self.app.canvas.annotation_type = ShapeType.MARKER
        if self.marker_tool:
            self.marker_tool.destroy()
        self.marker_tool = MarkerDialog(self.app)
        self.marker_tool.show()

    def scale_button(
        self, button: ttk.Button, image_enum: ImageEnum = None, image_file: str = None
    ) -> None:
        image = None
        if image_enum:
            image = self.app.get_icon(image_enum, TOOLBAR_SIZE)
        elif image_file:
            image = self.app.get_custom_icon(image_file, TOOLBAR_SIZE)
        if image:
            button.config(image=image)
            button.image = image

    def scale(self) -> None:
        self.scale_button(self.play_button, ImageEnum.START)
        self.scale_button(self.select_button, ImageEnum.SELECT)
        self.scale_button(self.link_button, ImageEnum.LINK)
        if self.node_enum:
            self.scale_button(self.node_button, self.node_enum)
        if self.node_file:
            self.scale_button(self.node_button, image_file=self.node_file)
        self.scale_button(self.network_button, self.network_enum)
        self.scale_button(self.annotation_button, self.annotation_enum)
        self.scale_button(self.runtime_select_button, ImageEnum.SELECT)
        self.scale_button(self.stop_button, ImageEnum.STOP)
        self.scale_button(self.runtime_marker_button, ImageEnum.MARKER)
        self.scale_button(self.run_command_button, ImageEnum.RUN)
