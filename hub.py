import os

from PyQt5 import QtCore, QtWidgets, QtGui

import main_windows
import popups
import workers
from appinfo import SHIP_STATS


class Hub(QtCore.QObject):
    script_settings = QtCore.pyqtSignal(tuple)  # worker settings from SettingsPop
    script_mode_signal = QtCore.pyqtSignal(bool)
    window_quit_signal = QtCore.pyqtSignal(bool)  # if window was closed, close ahk script
    worker_set_ahk_signal = QtCore.pyqtSignal()
    save_route_signal = QtCore.pyqtSignal()  # signal to save current route
    quit_worker_signal = QtCore.pyqtSignal()

    stop_alert_worker_signal = QtCore.pyqtSignal()
    alert_fuel_signal = QtCore.pyqtSignal(int, int)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.application = QtWidgets.QApplication.instance()
        self.jpath = self.settings.value("paths/journal")
        self.dark = self.settings.value("window/dark", type=bool)

        self.save_on_quit = self.settings.value("save_on_quit", type=bool)
        self.sound_alert = self.settings.value("alerts/audio", type=bool)
        self.visual_alert = self.settings.value("alerts/visual", type=bool)
        self.sound_path = self.settings.value("paths/alert")
        self.modifier = self.settings.value("alerts/threshold", type=int)

        self.last_index = 0
        self.total_jumps = 0
        self.max_fuel = 999
        self.workers_started = False

        self.main_window = main_windows.MainWindow(self, self.dark)

    def startup(self):
        self.set_theme()
        self.write_default_settings()
        self.double_signal = self.main_window.double_signal
        self.edit_signal = self.main_window.edit_signal
        self.next_jump_signal = self.main_window.next_jump_signal
        self.show_window()
        self.initial_pop()

    def new_route(self):
        if self.workers_started:
            self.quit_worker_signal.emit()
            self.worker.quit()
            if any((self.visual_alert, self.sound_alert)):
                self.stop_alert_worker()
        self.main_window.reset_table()
        self.initial_pop()

    def show_window(self):
        self.main_window.resize(self.settings.value("window/size", type=QtCore.QSize))
        self.main_window.move(self.settings.value("window/pos", type=QtCore.QPoint))
        font = self.settings.value("font/font", type=QtGui.QFont)
        font.setPointSize(self.settings.value("font/size", type=int))
        font.setBold(self.settings.value("font/bold", type=bool))
        self.main_window.MainTable.setFont(font)
        self.main_window.show()

    def start_alert_worker(self):
        self.player = workers.SoundPlayer(self.sound_path)
        status_file = (f"{os.environ['userprofile']}/Saved Games/"
                       f"Frontier Developments/Elite Dangerous/Status.json")
        self.sound_worker = workers.FuelAlert(self, self.max_fuel, status_file, self.modifier)
        self.sound_worker.alert_signal.connect(self.fuel_alert)
        self.sound_worker.start()

    def stop_alert_worker(self):
        self.stop_alert_worker_signal.emit()
        self.sound_worker.quit()
        try:
            self.sound_worker.alert_signal.disconnect()
        except TypeError:
            pass

    def set_max_fuel(self, value):
        self.max_fuel = value

    def fuel_alert(self):
        if self.visual_alert:
            self.application.alert(self.centralwidget, 5000)
        if self.sound_alert:
            if self.sound_path:
                self.player.play()
            else:
                self.application.beep()

    def start_worker(self, journal, data_values, index):
        settings = (self.settings.value("script"), self.settings.value("bind"),
                    self.dark, self.settings.value("copy_mode", type=bool))
        self.worker = workers.AhkWorker(self, journal, data_values, settings, index)
        self.worker.sys_signal.connect(self.main_window.grayout)
        self.worker.route_finished_signal.connect(self.end_route_pop)
        self.worker.game_shut_signal.connect(self.restart_worker)
        self.worker.fuel_signal.connect(self.get_max_fuel)
        self.worker.start()

        if self.visual_alert or self.sound_alert:
            self.start_alert_worker()
        self.workers_started = True

    def restart_worker(self, route_data, route_index):
        self.worker.quit()
        if self.sound_alert or self.visual_alert:
            self.stop_alert_worker()
        while not self.worker.isFinished():
            QtCore.QThread.sleep(1)
        w = popups.GameShutPop(self.main_window, self.settings, route_data, route_index)
        w.show()
        w.worker_signal.connect(self.start_worker)
        w.close_signal.connect(self.main_window.disconnect_signals)

    def get_max_fuel(self, json):
        fsd = next(item for item in json['Modules'] if item['Slot'] == "FrameShiftDrive")
        self.max_fuel = SHIP_STATS['FSD'][fsd['Item']][0]
        if 'Engineering' in fsd:
            for blueprint in fsd['Engineering']['Modifiers']:
                if blueprint['Label'] == 'MaxFeulPerJump':
                    self.max_fuel = blueprint['Value']

        self.alert_fuel_signal.emit(self.max_fuel, self.modifier)

    def set_theme(self):
        """ Set dark/default theme depending on user setting"""
        if self.dark:
            change_to_dark()
        else:
            change_to_default()

    def initial_pop(self):
        w = main_windows.PlotStartDialog(self.main_window, self.settings)
        w.fuel_signal.connect(self.set_max_fuel)
        w.data_signal.connect(self.main_window.pop_table)
        w.setup_ui()
        w.show()

    def end_route_pop(self):
        w = popups.RouteFinishedPop(self.main_window)
        w.show()
        w.close_signal.connect(self.disconnect_signals)
        w.new_route_signal.connect(self.new_route)

    def licenses_pop(self):
        w = popups.LicensePop(self.main_window)
        w.show()

    def sett_pop(self):
        w = popups.SettingsPop(self.main_window, self.settings)
        w.show()
        w.settings_signal.connect(self.change_editable_settings)

    def change_editable_settings(self, values):
        self.script_mode_signal.emit(values[7])
        self.script_settings.emit((values[0], values[1], values[2]))

        self.dark = values[2]
        self.set_theme()

        if (values[8] or values[9]
                and not any((self.sound_alert, self.visual_alert))):
            self.start_alert_worker()
        elif not values[8] and not values[9]:
            self.stop_alert_worker()
        self.sound_alert = values[8]
        self.visual_alert = values[9]

        self.save_on_quit = values[6]
        if any((self.sound_alert, self.visual_alert)):
            self.stop_alert_worker()
            self.start_alert_worker()

        self.modifier = values[10]
        self.alert_fuel_signal.emit(self.max_fuel, self.modifier)

        self.sound_path = values[11]
        self.player = workers.SoundPlayer(values[11])

        font = values[3]
        font.setPointSize(values[4])
        font.setBold(values[5])
        self.main_window.change_settings(font, self.dark)

    def write_default_settings(self):
        if not self.settings.value("paths/journal"):
            self.resize(800, 600)
            self.move(300, 300)
            self.settings.setValue("paths/journal",
                                   (f"{os.environ['userprofile']}/Saved Games/"
                                    f"Frontier Developments/Elite Dangerous/"))
            self.jpath = (f"{os.environ['userprofile']}/Saved Games/"
                          f"Frontier Developments/Elite Dangerous/")
            self.settings.setValue("paths/ahk",
                                   (f"{os.environ['PROGRAMW6432']}/"
                                    f"AutoHotkey/AutoHotkey.exe"))
            self.settings.setValue("save_on_quit", True)
            self.settings.setValue("paths/csv", "")
            self.settings.setValue("window/size", QtCore.QSize(800, 600))
            self.settings.setValue("window/pos", QtCore.QPoint(100, 100))
            self.settings.setValue("window/dark", False)
            self.settings.setValue("window/font_size", 11)
            self.settings.setValue("font/font", QtGui.QFont())
            self.settings.setValue("font/size", 11)
            self.settings.setValue("font/bold", False)
            self.settings.setValue("bind", "F5")
            self.settings.setValue("alerts/audio", False)
            self.settings.setValue("alerts/visual", False)
            self.settings.setValue("alerts/threshold", 150)
            self.settings.setValue("paths/alert", "")
            self.settings.setValue("script", ("SetKeyDelay, 50, 50\n"
                                              ";bind to open map\n"
                                              "send, {Numpad7}\n"
                                              "; wait for map to open\n"
                                              "sleep, 850\n"
                                              ";navigate to second map tab "
                                              "and focus on search field\n"
                                              "send, e\n"
                                              "send, {Space}\n"
                                              "ClipOld := ClipboardAll\n"
                                              'Clipboard := "|SYSTEMDATA|"\n'
                                              "sleep, 100\n"
                                              "Send, ^v\n"
                                              "Clipboard := ClipOld\n"
                                              "ClipOld ="
                                              "SetKeyDelay, 1, 2\n"
                                              "send, {enter}\n"))
            self.settings.setValue("last_route", ())
            self.settings.sync()
            self.write_ahk_path()

    def quit(self, size, pos):
        self.settings.setValue("window/size", size)
        self.settings.setValue("window/pos", pos)
        self.settings.sync()
        self.window_quit_signal.emit(self.save_on_quit)

    def write_ahk_path(self):
        if not os.path.exists((self.settings.value("paths/ahk"))):
            ahk_path = QtWidgets.QFileDialog.getOpenFileName(
                filter="AutoHotKey (AutoHotKey*.exe)",
                caption="Select AutoHotkey's executable "
                        "if you wish to use it, cancel for copy mode",
                directory="C:/")

            if len(ahk_path[0]) == 0:
                self.settings.setValue("copy_mode", True)
                self.settings.setValue("paths/AHK", "")
            else:
                self.settings.setValue("paths/AHK", ahk_path[0])
                self.settings.setValue("copy_mode", False)
            self.settings.sync()


def change_to_dark():
    p = QtGui.QPalette()
    p.setColor(QtGui.QPalette.Window, QtGui.QColor(53, 53, 53))
    p.setColor(QtGui.QPalette.WindowText, QtGui.QColor(247, 247, 247))
    p.setColor(QtGui.QPalette.Base, QtGui.QColor(25, 25, 25))
    p.setColor(QtGui.QPalette.Text, QtGui.QColor(247, 247, 247))
    p.setColor(QtGui.QPalette.Button, QtGui.QColor(60, 60, 60))
    p.setColor(QtGui.QPalette.Background, QtGui.QColor(35, 35, 35))
    p.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(45, 45, 45))
    p.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.white)
    p.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
    app = QtWidgets.QApplication.instance()
    app.setStyle("Fusion")
    app.setPalette(p)


def change_to_default():
    app = QtWidgets.QApplication.instance()
    app.setStyle("Fusion")
    app.setPalette(app.style().standardPalette())
