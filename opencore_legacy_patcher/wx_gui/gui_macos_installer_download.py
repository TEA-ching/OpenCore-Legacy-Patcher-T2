"""
gui_macos_installer_download.py: macOS Installer Download Frame
"""

import wx
import locale
import logging
import threading
import webbrowser
import sys

from pathlib import Path

from .. import (
    constants,
    sucatalog
)

from ..datasets import (
    os_data,
    smbios_data,
    cpu_data
)
from ..wx_gui import (
    gui_main_menu,
    gui_support,
    gui_download,
    gui_macos_installer_flash
)
from ..support import (
    macos_installer_handler,
    utilities,
    network_handler,
    integrity_verification
)


class macOSInstallerDownloadFrame(wx.Frame):
    """
    Create a frame for downloading and creating macOS installers
    Uses a Modal Dialog for smoother transition from other frames
    Note: Flashing installers is passed to gui_macos_installer_flash.py
    """
    def __init__(self, parent: wx.Frame, title: str, global_constants: constants.Constants, screen_location: tuple = None):
        logging.info("Initializing macOS Installer Download Frame")
        super(macOSInstallerDownloadFrame, self).__init__(parent, title=title, size=(300, 200), style=wx.DEFAULT_FRAME_STYLE & ~(wx.RESIZE_BORDER | wx.MAXIMIZE_BOX))
        
        self.constants: constants.Constants = global_constants
        self.title: str = title
        self.parent: wx.Frame = parent

        self.catalog_products = None
        self.available_installers = None
        self.available_installers_latest = None

        self.catalog_seed: sucatalog.SeedType = sucatalog.SeedType.DeveloperSeed

        self.frame_modal = wx.Dialog(parent, title=title, size=(330, 200))

        self._generate_elements(self.frame_modal)
        self.frame_modal.ShowWindowModal()

        self.icons = [[self._icon_to_bitmap(i), self._icon_to_bitmap(i, (64, 64))] for i in self.constants.icons_path]

    def _icon_to_bitmap(self, icon: str, size: tuple = (32, 32)) -> wx.Bitmap:
        """
        Convert icon to bitmap
        """
        return wx.Bitmap(wx.Bitmap(icon, wx.BITMAP_TYPE_ICON).ConvertToImage().Rescale(size[0], size[1], wx.IMAGE_QUALITY_HIGH))

    def _macos_version_to_icon(self, version: int) -> int:
        """
        Convert macOS version to icon
        """
        try:
            self.constants.icons_path[version - 19]
            return version - 19
        except IndexError:
            return 0

    def _generate_elements(self, frame: wx.Frame = None) -> None:
        frame = self if not frame else frame

        title_label = wx.StaticText(frame, label="Create macOS Installer", pos=(-1, 5))
        title_label.SetFont(gui_support.font_factory(19, wx.FONTWEIGHT_BOLD))
        title_label.Centre(wx.HORIZONTAL)

        download_button = wx.Button(frame, label="Download macOS Installer", pos=(-1, title_label.GetPosition()[1] + title_label.GetSize()[1] + 5), size=(200, 30))
        download_button.Bind(wx.EVT_BUTTON, self.on_download)
        download_button.Centre(wx.HORIZONTAL)

        existing_button = wx.Button(frame, label="Use existing macOS Installer", pos=(-1, download_button.GetPosition()[1] + download_button.GetSize()[1] - 5), size=(200, 30))
        existing_button.Bind(wx.EVT_BUTTON, self.on_existing)
        existing_button.Centre(wx.HORIZONTAL)

        return_button = wx.Button(frame, label="Return to Main Menu", pos=(-1, existing_button.GetPosition()[1] + existing_button.GetSize()[1] + 5), size=(150, 30))
        return_button.Bind(wx.EVT_BUTTON, self.on_return)
        return_button.Centre(wx.HORIZONTAL)

        frame.SetSize((-1, return_button.GetPosition()[1] + return_button.GetSize()[1] + 40))

    def _generate_catalog_frame(self) -> None:
        """
        Generate frame to display available installers asynchronously
        """
        gui_support.GenerateMenubar(self, self.constants).generate()
        self.Centre()

        title_label = wx.StaticText(self, label="Finding Available Software", pos=(-1, 5))
        title_label.SetFont(gui_support.font_factory(19, wx.FONTWEIGHT_BOLD))
        title_label.Centre(wx.HORIZONTAL)

        self.progress_bar = wx.Gauge(self, range=100, pos=(-1, title_label.GetPosition()[1] + title_label.GetSize()[1] + 5), size=(250, 30))
        self.progress_bar.Centre(wx.HORIZONTAL)
        self.progress_bar_animation = gui_support.GaugePulseCallback(self.constants, self.progress_bar)
        self.progress_bar_animation.start_pulse()

        self.SetSize((-1, self.progress_bar.GetPosition()[1] + self.progress_bar.GetSize()[1] + 40))
        self.Show()

        def _fetch_installers():
            logging.info(f"Fetching AppleDB products")
            self.catalog_products = sucatalog.AppleDBProducts(self.constants)
            
            if self.catalog_products.data is None:
                logging.error("Failed to fetch installers from AppleDB")
                wx.CallAfter(self._on_fetch_failed)
                return

            self.available_installers = self.catalog_products.products
            self.available_installers_latest = self.catalog_products.latest_products
            
            # FIX: Sicherer Rückruf in den Haupt-Thread nach Beendigung des Netzwerkvorgangs
            wx.CallAfter(self._on_fetch_success)

        thread = threading.Thread(target=_fetch_installers)
        self.constants.add_thread(thread)  # Falls eine Thread-Tracking-Methode existiert
        thread.start()

    def _on_fetch_failed(self):
        self.progress_bar_animation.stop_pulse()
        self.progress_bar.Hide()
        wx.MessageBox("Failed to fetch installers from AppleDB", "Error", wx.OK | wx.ICON_ERROR, self)
        self.on_return_to_main_menu()

    def _on_fetch_success(self):
        self.progress_bar_animation.stop_pulse()
        self.progress_bar.Hide()
        self._display_available_installers()

    def _display_available_installers(self, event: wx.Event = None, show_full: bool = False) -> None:
        bundles = [wx.BitmapBundle.FromBitmaps(icon) for icon in self.icons]

        if self.frame_modal:
            self.frame_modal.Destroy()
            
        self.frame_modal = wx.Dialog(self, title="Select macOS Installer", size=(550, 500))

        title_label = wx.StaticText(self.frame_modal, label="Select macOS Installer", pos=(-1, -1))
        title_label.SetFont(gui_support.font_factory(19, wx.FONTWEIGHT_BOLD))

        # Modernes ID-Handling für wxPython v4+
        list_id = wx.NewIdRef() if hasattr(wx, "NewIdRef") else wx.NewId()

        self.list = wx.ListCtrl(self.frame_modal, list_id, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_NO_HEADER | wx.BORDER_SUNKEN)
        self.list.SetSmallImages(bundles)

        self.list.InsertColumn(0, "Title", width=190 if show_full else 150)
        self.list.InsertColumn(1, "Version", width=80 if show_full else 50)
        self.list.InsertColumn(2, "Build", width=75)
        self.list.InsertColumn(3, "Size", width=75)
        self.list.InsertColumn(4, "Release Date", width=100)

        installers = self.available_installers_latest if show_full is False else self.available_installers
        if show_full is False:
            self.frame_modal.SetSize((480, 370))

        if installers:
            try:
                locale.setlocale(locale.LC_TIME, '')
            except Exception:
                pass
            logging.info(f"Available installers from AppleDB ({'All entries' if show_full else 'Latest only'}):")
            for item in installers:
                index = self.list.InsertItem(self.list.GetItemCount(), f"{item['Title']}")
                self.list.SetItemImage(index, self._macos_version_to_icon(int(item['Build'][:2])))
                self.list.SetItem(index, 1, item['Version'])
                self.list.SetItem(index, 2, item['Build'])
                self.list.SetItem(index, 3, utilities.human_fmt(item['InstallAssistant']['Size']))
                self.list.SetItem(index, 4, item['PostDate'].strftime("%x"))
        else:
            logging.error("No installers found from AppleDB")
            wx.MessageDialog(self.frame_modal, "Failed to fetch installers from AppleDB", "Error", wx.OK | wx.ICON_ERROR).ShowModal()

        if show_full is False:
            self.list.Select(-1)

        self.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_select_list)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select_list)

        self.select_button = wx.Button(self.frame_modal, label="Download", pos=(-1, -1), size=(150, -1))
        self.select_button.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        self.select_button.Bind(wx.EVT_BUTTON, lambda event, installers=installers: self.on_download_installer(installers))
        self.select_button.SetToolTip("Download the selected macOS Installer.")
        self.select_button.SetDefault()
        if show_full is True:
            self.select_button.Disable()

        self.copy_button = wx.Button(self.frame_modal, label="Copy Link", pos=(-1, -1), size=(80, -1))
        self.copy_button.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))
        if show_full is True:
            self.copy_button.Disable()
        self.copy_button.SetToolTip("Copy the download link of the selected macOS Installer.")
        self.copy_button.Bind(wx.EVT_BUTTON, lambda event, installers=installers: self.on_copy_link(installers))

        return_button = wx.Button(self.frame_modal, label="Return to Main Menu", pos=(-1, -1), size=(150, -1))
        return_button.Bind(wx.EVT_BUTTON, self.on_return_to_main_menu)
        return_button.SetFont(gui_support.font_factory(13, wx.FONTWEIGHT_NORMAL))

        self.showolderversions_checkbox = wx.CheckBox(self.frame_modal, label="Show Older/Beta Versions", pos=(-1, -1))
        if show_full is True:
            self.showolderversions_checkbox.SetValue(True)
        self.showolderversions_checkbox.Bind(wx.EVT_CHECKBOX, lambda event: self._display_available_installers(event, self.showolderversions_checkbox.GetValue()))

        rectbox = wx.StaticBox(self.frame_modal, -1)
        rectsizer = wx.StaticBoxSizer(rectbox, wx.HORIZONTAL)
        rectsizer.Add(self.copy_button, 0, wx.EXPAND | wx.RIGHT, 5)
        rectsizer.Add(self.select_button, 0, wx.EXPAND | wx.LEFT, 5)

        checkboxsizer = wx.BoxSizer(wx.HORIZONTAL)
        checkboxsizer.Add(self.showolderversions_
