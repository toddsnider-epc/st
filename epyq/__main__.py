#!/usr/bin/env python3

# TODO: get some docstrings in here!

# TODO: CAMPid 98852142341263132467998754961432
import epyq.tee
import os
import sys

log = open(os.path.join(os.getcwd(), 'epyq.log'), 'w', encoding='utf-8')

if sys.stdout is None:
    sys.stdout = log
else:
    sys.stdout = epyq.tee.Tee([sys.stdout, log])

if sys.stderr is None:
    sys.stderr = log
else:
    sys.stderr = epyq.tee.Tee([sys.stderr, log])

try:
    import epyq.revision
except ImportError:
    pass
else:
    print(epyq.revision.hash)

import can
import canmatrix.importany as importany
import copy
import epyq.busproxy
import epyq.canneo
import epyq.device
import epyq.hmidialog
import epyq.listmenuview
import epyq.numberpad
import epyq.nv
import epyq.parameteredit

try:
    import epyq.revision
except ImportError:
    pass

from epyq.svgwidget import SvgWidget
import epyq.txrx
import epyq.wehmd
import functools
import io
import math
import platform
import socket
import subprocess
import textwrap
# TODO: figure out why this is negative on embedded... :[
socket.CAN_EFF_FLAG = abs(socket.CAN_EFF_FLAG)

from PyQt5 import QtCore, QtWidgets, QtGui, uic
from PyQt5.QtCore import (QFile, QFileInfo, QTextStream, QCoreApplication,
                          QSettings, Qt, pyqtSlot, QMarginsF, QTextCodec)
from PyQt5.QtWidgets import (QApplication, QMessageBox, QFileDialog, QLabel,
                             QListWidgetItem, QAction, QMenu, QFrame,
                             QAbstractScrollArea, QWidget)
from PyQt5.QtGui import QPixmap, QPicture
import time
import traceback

# See file COPYING in this source tree
__copyright__ = 'Copyright 2016, EPC Power Corp.'
__license__ = 'GPLv2+'


def load_ui(filename):
    # TODO: CAMPid 9549757292917394095482739548437597676742
    if not QFileInfo(filename).isAbsolute():
        ui_file = os.path.join(
            QFileInfo.absolutePath(QFileInfo(__file__)), filename)
    else:
        ui_file = filename
    ui_file = QFile(ui_file)
    ui_file.open(QFile.ReadOnly | QFile.Text)
    ts = QTextStream(ui_file)
    sio = io.StringIO(ts.readAll())
    return uic.loadUi(sio)


def main(args=None):
    print('starting epyq')

    app = QApplication(sys.argv)
    app.setOrganizationName('EPC Power Corp.')
    app.setApplicationName('EPyQ')

    base_font_size_px = 30

    QTextCodec.setCodecForLocale(QTextCodec.codecForName('UTF-8'))

    ui = load_ui('main.ui')

    bus = epyq.busproxy.BusProxy()

    device_file = 'example_hmi.epc'
    # TODO: CAMPid 9549757292917394095482739548437597676742
    if not QFileInfo(device_file).isAbsolute():
        device_file = os.path.join(
            os.getcwd(), device_file)
    else:
        device_file = device_file

    def add_stacked_widget(widget):
        ui.stacked.addWidget(widget)
        widget.setProperty('is_stacked_widget', True)

    number_pad = epyq.numberpad.NumberPad()
    add_stacked_widget(number_pad)


    def set_widget_value(dash, widget, value):
        if value is not None:
            widget.signal_object.set_human_value(value)
        ui.stacked.setCurrentWidget(dash)

    def trigger_numberpad(dash, widget):
        number_pad.focus(value=widget.signal_object.get_human_value(),
                         action=functools.partial(
                             set_widget_value, widget=widget, dash=dash),
                         label='{} [{}]'.format(widget.ui.label.text(),
                                                widget.ui.units.text()))

    def connect_to_numberpad(dash, widget, signal):
        signal.connect(functools.partial(
            trigger_numberpad,
            dash=dash,
            widget=widget
        ))

    device = epyq.device.Device(file=device_file,
                                bus=bus,
                                tabs=[],
                                elements=[epyq.device.Elements.dash,
                                          epyq.device.Elements.nv],
                                rx_interval=1,
                                edit_action=connect_to_numberpad)
    # TODO: CAMPid 9757656124812312388543272342377

    interface = 'socketcan'
    channel = 'can0'

    # TODO: CAMPid 9756652312918432656896822
    if interface != 'offline':
        real_bus = can.interface.Bus(bustype=interface, channel=channel,
                                     can_filters=[])
    else:
        real_bus = None
    bus.set_bus(bus=real_bus)

    import json
    from collections import OrderedDict

    with open('menu.json') as f:
        menu = json.load(f, object_pairs_hook=OrderedDict)

    def to_menu():
        real_bus.setFilters(can_filters=[])
        ui.stacked.setCurrentWidget(menu)

    ui.menu_button.clicked.connect(to_menu)

    special_menu_nodes = {}

    hmi_dialog = epyq.hmidialog.HmiDialog()

    nv_filters = [
        {
            'can_id': device.nvs.status_frames[0].id | socket.CAN_EFF_FLAG,
            'can_mask': socket.CAN_EFF_MASK |
                        socket.CAN_EFF_FLAG |
                        socket.CAN_RTR_FLAG
        }
    ]

    def focus_nv(widget):
        real_bus.setFilters(nv_filters)

        widget.nv.read_from_device()
        ui.stacked.setCurrentWidget(widget)

    def nv_action(node):
        for nv in device.nvs.children:
            widget = epyq.parameteredit.ParameterEdit(
                edit=number_pad,
                nv=nv,
                dialog=hmi_dialog)

            add_stacked_widget(widget)
            nv_node = epyq.listmenu.Node(
                text=nv.name,
                action=functools.partial(
                    focus_nv,
                    widget=widget
                )
            )
            node.append_child(nv_node)

    special_menu_nodes['<nv>'] = nv_action

    def service_restart():
        hmd = epyq.wehmd.Wehmd()
        hmd.write_boot_mode(1)
        subprocess.run('reboot')

    def service_reboot_action(node):
        node.action = functools.partial(
                hmi_dialog.focus,
                ok_action=service_restart,
                cancel_action=to_menu,
                label=textwrap.dedent('''\
                    Reboot into maintenance mode?

                    Insert configured USB stick then press OK.''')
        )

    special_menu_nodes['<service_reboot>'] = service_reboot_action

    def calibrate_touchscreen():
        os.remove('/opt/etc/pointercal')
        subprocess.run('reboot')

    def calibrate_touchscreen_action(node):
        node.action = functools.partial(
                hmi_dialog.focus,
                ok_action=calibrate_touchscreen,
                cancel_action=to_menu,
                label=textwrap.dedent('''\
                    Reboot and calibrate touchscreen?''')
        )

    special_menu_nodes['<calibrate_touchscreen>'] = calibrate_touchscreen_action

    # TODO: CAMPid 93849811216123127753953680713426
    def inverter_to_nv():
        device.nvs.module_to_nv()
        to_menu()

    def inverter_to_nv_action(node):
        node.action = functools.partial(
                hmi_dialog.focus,
                ok_action=inverter_to_nv,
                cancel_action=to_menu,
                label=textwrap.dedent('''\
                    Save all parameters to NV?''')
        )

    special_menu_nodes['<nv_save>'] = inverter_to_nv_action

    message = [
        'About EPyQ:',
        __copyright__,
        __license__
    ]

    try:
        hash = epyq.revision.hash
    except AttributeError:
        pass
    else:
        index = round(len(hash) / 2)
        hash = '({first}<br>{second})'.format(first=hash[:index],
                                              second=hash[index:])
        message.append(hash)

    about_text = '<br>'.join(message)
    about_text = "<span style='font-size:{px}px'>{text}</span>".format(
        text=about_text,
        px=round(base_font_size_px * 2/3)
    )

    def about_action(node):
        node.action = functools.partial(
            hmi_dialog.focus,
            ok_action=to_menu,
            enable_delay=0,
            label=about_text
        )

    special_menu_nodes['<about>'] = about_action

    menu_root = epyq.listmenu.Node(text='Main Menu')

    def focus_dash(dash):
        filters = [
            {
                'can_id': frame.id | socket.CAN_EFF_FLAG,
                'can_mask': socket.CAN_EFF_MASK |
                            socket.CAN_EFF_FLAG |
                            socket.CAN_RTR_FLAG
            }
            for frame in dash.connected_frames
        ]
        real_bus.setFilters(filters)
        ui.stacked.setCurrentWidget(dash)

    def traverse(dict_node, model_node):
        for key, value in dict_node.items():
            child = epyq.listmenu.Node(text=key)
            model_node.append_child(child)
            if isinstance(value, OrderedDict):
                traverse(dict_node=value,
                         model_node=child)
            elif value.endswith('.ui'):
                # TODO: CAMPid
                for dash in device.dash_uis.values():
                    if dash.file_name == value:
                        add_stacked_widget(dash)
                        child.action = functools.partial(
                            focus_dash,
                            dash=dash
                        )
            else:
                try:
                    special_node = special_menu_nodes[value]
                except KeyError:
                    print("No menu action '{}' found in {}".format(
                            value,
                            special_menu_nodes.keys()),
                        file=sys.stderr
                    )
                else:
                    special_node(child)

    traverse(menu, menu_root)

    menu_model = epyq.listmenu.ListMenuModel(root=menu_root)
    menu = epyq.listmenuview.ListMenuView()
    menu.setModel(menu_model)
    add_stacked_widget(menu)

    dash = [d for d in device.dash_uis.values() if
            d.file_name == device.raw_dict['dash']][0]

    add_stacked_widget(dash)

    ui.dash_button.clicked.connect(
        functools.partial(
            focus_dash,
            dash=dash
        )
    )


    ui.stacked.setCurrentWidget(menu)

    add_stacked_widget(hmi_dialog)

    ui.offline_overlay = epyq.overlaylabel.OverlayLabel(parent=ui)
    ui.offline_overlay.label.setText('')

    for widget in ui.findChildren(QWidget):
        widget.setProperty('fontawesome',
                           widget.font().family() == 'FontAwesome')
        if widget.property('style_small'):
            widget.setStyleSheet('''
                QWidget[fontawesome=false] {{
                    border-radius: 5px;
                    font-size: 15px;
                }}
            '''.format())

        # TODO: CAMPid 97453289314763416967675427
        if widget.property('editable'):
            dash = widget.parent()
            while dash is not None:
                if dash.property('is_stacked_widget'):
                    break

                dash = dash.parent()

            connect_to_numberpad(dash=dash,
                                 widget=widget,
                                 signal=widget.edit)

    app.setStyleSheet('''
        QWidget {{
            font-size: {base_font_size_px}px;
            qproperty-focusPolicy: NoFocus;
            color: black;
            background: {background};
        }}

        QWidget[fontawesome=false] {{
            font-family: Bitstream Vera Sans;
        }}

        QAbstractScrollArea {{
            qproperty-frameShape: NoFrame;
        }}

        QPushButton {{
            font-size: {base_font_size_px}px;
            min-width: 40px;
            min-height: 40px;
        }}

        QSlider {{
            min-height: 60px;
            min-width: 30px;
        }}

        QPushButton[fontawesome=true] {{
            min-width: 40px;
            max-width: 40px;
            min-height: 40px;
            max-height: 40px;
        }}

        QFrame {{
            qproperty-frameShadow: Plain;
        }}

        QLineEdit, QPushButton {{
            border-radius: 10px;
            border-width: 0px;
            border-style: solid;
        }}

        QLineEdit {{
            qproperty-focusPolicy: NoFocus;
            background-color: {blue};
        }}

        QPushButton:enabled {{
            background-color: {green};
        }}

        QPushButton:!enabled {{
            background-color: gray;
        }}

        QLineEdit {{
            qproperty-frame: false;
        }}

        QLineEdit:!enabled {{
            background-color: gray;
        }}

        QLineEdit:enabled {{
            padding: 0 8px;
            selection-background-color: darkgray;
        }}

        QSlider::groove {{
            width: 4px;
            border-radius: 2px;
            background-color: gray;
        }}

        QSlider::handle {{
            height: 10px;
            border-radius: 3px;
            margin: 0 -8px;
            background-color: {blue};
        }}
    '''.format(
        base_font_size_px=base_font_size_px,
        background='hsva(0%, 0%, 80%)',
        blue='hsva(80%, 80%, 65%, 50%)',
        green='hsva(57%, 80%, 65%, 50%)'
    ))

    if os.environ.get('QT_QPA_PLATFORM', None) == 'linuxfb':
        ui.showFullScreen()
    else:
        ui.show()

    # TODO: CAMPid 98754713241621231778985432
    # ui.menu_button.setMaximumWidth(ui.menu_button.height())

    menu.update_calculated_layout()

    return app.exec_()

if __name__ == '__main__':
    sys.exit(main())
