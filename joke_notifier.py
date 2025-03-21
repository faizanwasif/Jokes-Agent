import sys
import os
import json
import time
import threading
import requests
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QFrame, QListWidget, QScrollArea, 
    QDialog, QRadioButton, QCheckBox, QSlider, QGroupBox, 
    QMessageBox, QGridLayout, QTextEdit, QSplitter, QSystemTrayIcon, QMenu
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QSize
from PyQt6.QtGui import QIcon, QColor, QPainter, QPixmap, QFont, QPalette

# Import notification libraries based on what's available
try:
    # For Windows 10+, use win10toast_click which has better Windows support
    import win10toast_click
    toaster = win10toast_click.ToastNotifier()
    NOTIFICATION_SYSTEM = "win10toast_click"
except ImportError:
    try:
        # Fall back to standard win10toast
        import win10toast
        toaster = win10toast.ToastNotifier()
        NOTIFICATION_SYSTEM = "win10toast"
    except ImportError:
        try:
            # Try plyer as the next option
            from plyer import notification
            NOTIFICATION_SYSTEM = "plyer"
        except ImportError:
            try:
                # Linux-specific option
                import notify2
                notify2.init("Joke Notifier")
                NOTIFICATION_SYSTEM = "notify2"
            except ImportError:
                # Final fallback to Qt's own system
                NOTIFICATION_SYSTEM = "qt"


# Signal class to safely update UI from threads
class SignalBridge(QObject):
    update_status = pyqtSignal(str)
    update_next_joke_time = pyqtSignal(str)
    add_joke = pyqtSignal(dict)


class JokeNotifier(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Variables
        self.is_running = False
        self.joke_thread = None
        self.last_jokes = []
        self.max_stored_jokes = 15
        
        # Default settings
        self.settings = {
            "frequency": 30,  # minutes
            "categories": ["Any"],
            "safe_mode": True,
            "joke_type": "Any",
            "language": "en",
            "autostart": False,
            "notification_duration": 10,
            "max_history": 15
        }
        
        # Create signal bridge
        self.signal_bridge = SignalBridge()
        self.signal_bridge.update_status.connect(self.update_status)
        self.signal_bridge.update_next_joke_time.connect(self.update_next_joke_time)
        self.signal_bridge.add_joke.connect(self.add_joke_to_list)
        
        # Setup UI
        self.setWindowTitle("Joke Notifier")
        self.setMinimumSize(500, 600)
        
        # Set app icon if available
        try:
            icon_path = os.path.join(os.path.dirname(__file__), "icon.ico")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass
        
        # Create main widget and layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)
        
        # Create UI elements
        self.create_widgets()
        
        # Load settings if they exist
        self.load_settings()
        
        # Setup system tray
        self.setup_system_tray()
        
        # Start automatically if enabled
        if self.settings.get("autostart", False):
            QTimer.singleShot(1000, self.start_notifications)
    
    def create_widgets(self):
        # Title and status frame
        title_frame = QHBoxLayout()
        
        # Title
        title_label = QLabel("Joke Notifier")
        title_label.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        title_frame.addWidget(title_label)
        
        # Status indicator (colored circle)
        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(20, 20)
        self.update_status_indicator("red")
        title_frame.addWidget(self.status_indicator)
        
        self.main_layout.addLayout(title_frame)
        
        # Description
        desc_label = QLabel("Get jokes as desktop notifications while you work!\nJokes are filtered to avoid offensive content.")
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(desc_label)
        
        # Control frame
        control_frame = QHBoxLayout()
        
        # Start/Stop button
        self.toggle_button = QPushButton("Start Notifications")
        self.toggle_button.clicked.connect(self.toggle_notifications)
        self.toggle_button.setMinimumWidth(150)
        control_frame.addWidget(self.toggle_button)
        
        # Spacer
        control_frame.addStretch()
        
        # Test notification button
        self.test_button = QPushButton("Test Notification")
        self.test_button.clicked.connect(self.send_test_notification)
        control_frame.addWidget(self.test_button)
        
        # Settings button
        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.open_settings)
        control_frame.addWidget(self.settings_button)
        
        self.main_layout.addLayout(control_frame)
        
        # Status group
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout(status_group)
        
        self.status_label = QLabel("Ready to start")
        status_layout.addWidget(self.status_label)
        
        self.next_joke_label = QLabel("")
        status_layout.addWidget(self.next_joke_label)
        
        self.main_layout.addWidget(status_group)
        
        # Recent jokes group
        jokes_group = QGroupBox("Recent Jokes")
        jokes_layout = QVBoxLayout(jokes_group)
        
        self.jokes_listbox = QListWidget()
        self.jokes_listbox.setAlternatingRowColors(True)
        self.jokes_listbox.itemDoubleClicked.connect(self.show_full_joke)
        jokes_layout.addWidget(self.jokes_listbox)
        
        self.main_layout.addWidget(jokes_group)
        
        # Footer
        footer_label = QLabel("Powered by JokeAPI (https://jokeapi.dev)")
        footer_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        footer_label.setStyleSheet("color: gray; font-size: 8pt;")
        self.main_layout.addWidget(footer_label)
    
    def setup_system_tray(self):
        """Set up system tray icon and menu for better Windows integration"""
        # Create system tray icon
        self.tray_icon = QSystemTrayIcon(self)
        
        # Set icon - use application icon if available, otherwise use a default
        if not self.windowIcon().isNull():
            self.tray_icon.setIcon(self.windowIcon())
        else:
            self.tray_icon.setIcon(QIcon.fromTheme("dialog-information"))
        
        # Create tray menu
        tray_menu = QMenu()
        
        # Add actions
        show_action = tray_menu.addAction("Show Joke Notifier")
        show_action.triggered.connect(self.show_and_activate)
        
        tray_menu.addSeparator()
        
        toggle_action = tray_menu.addAction("Start Notifications")
        toggle_action.triggered.connect(self.toggle_notifications_from_tray)
        self.tray_toggle_action = toggle_action  # Save reference to update text later
        
        test_action = tray_menu.addAction("Send Test Notification")
        test_action.triggered.connect(self.send_test_notification)
        
        tray_menu.addSeparator()
        
        settings_action = tray_menu.addAction("Settings")
        settings_action.triggered.connect(self.open_settings)
        
        tray_menu.addSeparator()
        
        exit_action = tray_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)
        
        # Set the menu
        self.tray_icon.setContextMenu(tray_menu)
        
        # Handle activation (e.g., clicking the icon)
        self.tray_icon.activated.connect(self.tray_icon_activated)
        
        # Show the tray icon
        self.tray_icon.show()
        
        # Set tooltip
        self.tray_icon.setToolTip("Joke Notifier")

    def show_and_activate(self):
        """Show and activate the window"""
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.activateWindow()

    def toggle_notifications_from_tray(self):
        """Toggle notifications from the tray menu"""
        self.toggle_notifications()
        
        # Update tray menu text
        if self.is_running:
            self.tray_toggle_action.setText("Stop Notifications")
        else:
            self.tray_toggle_action.setText("Start Notifications")

    def tray_icon_activated(self, reason):
        """Handle tray icon activation"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Single click - show/hide the window
            if self.isVisible():
                self.hide()
            else:
                self.show_and_activate()
    
    def update_status_indicator(self, color):
        # Create a colored circle using a pixmap
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(2, 2, 16, 16)
        painter.end()
        
        self.status_indicator.setPixmap(pixmap)
    
    def toggle_notifications(self):
        if self.is_running:
            self.stop_notifications()
        else:
            self.start_notifications()
    
    def start_notifications(self):
        # Original start_notifications code
        self.is_running = True
        self.status_label.setText("Running - Sending notifications")
        self.toggle_button.setText("Stop Notifications")
        self.toggle_button.setStyleSheet("background-color: #ffcccc;")
        
        # Update status indicator
        self.update_status_indicator("green")
        
        # Update tray menu if it exists
        if hasattr(self, 'tray_toggle_action'):
            self.tray_toggle_action.setText("Stop Notifications")
        
        # Start the joke thread
        self.joke_thread = threading.Thread(target=self.joke_notification_loop, daemon=True)
        self.joke_thread.start()
    
    def stop_notifications(self):
        # Original stop_notifications code
        self.is_running = False
        self.status_label.setText("Stopped")
        self.toggle_button.setText("Start Notifications")
        self.toggle_button.setStyleSheet("background-color: #ccffcc;")
        self.next_joke_label.setText("")
        
        # Update status indicator
        self.update_status_indicator("red")
        
        # Update tray menu if it exists
        if hasattr(self, 'tray_toggle_action'):
            self.tray_toggle_action.setText("Start Notifications")
    
    def joke_notification_loop(self):
        # Send first joke immediately
        self.fetch_and_show_joke()
        
        # Then loop based on frequency
        while self.is_running:
            # Calculate next joke time
            next_joke_time = time.time() + (self.settings["frequency"] * 60)
            
            # Loop for updating the countdown
            while time.time() < next_joke_time and self.is_running:
                if not self.is_running:
                    return
                
                # Update countdown
                remaining = int(next_joke_time - time.time())
                mins = remaining // 60
                secs = remaining % 60
                self.signal_bridge.update_next_joke_time.emit(f"Next joke in: {mins}m {secs}s")
                
                # Sleep briefly
                time.sleep(1)
            
            # Fetch and show joke if still running
            if self.is_running:
                self.fetch_and_show_joke()
    
    def update_next_joke_time(self, message):
        self.next_joke_label.setText(message)
    
    def fetch_and_show_joke(self):
        try:
            # Build URL
            base_url = "https://v2.jokeapi.dev/joke/"
            categories = ",".join(self.settings["categories"])
            
            url = f"{base_url}{categories}?blacklistFlags=religious,racist,sexist,explicit"
            
            # Add parameters based on settings
            if self.settings["safe_mode"]:
                url += "&safe-mode"
            
            if self.settings["joke_type"] != "Any":
                url += f"&type={self.settings['joke_type'].lower()}"
            
            if self.settings["language"] != "en":
                url += f"&lang={self.settings['language']}"
            
            # Make the request
            response = requests.get(url)
            joke_data = response.json()
            
            # Check if there's an error
            if joke_data.get("error", False):
                error_message = joke_data.get("message", "Unknown error")
                self.signal_bridge.update_status.emit(f"Error: {error_message}")
                return
            
            # Format joke based on type
            if joke_data["type"] == "single":
                joke_text = joke_data["joke"]
                notification_title = "Joke Time!"
            else:  # twopart
                joke_text = f"{joke_data['setup']}\n\n{joke_data['delivery']}"
                notification_title = joke_data['setup']
                
                # If setup is too long for notification title, use generic title
                if len(notification_title) > 50:
                    notification_title = "Joke Time!"
            
            # Add category info
            category = joke_data.get("category", "")
            timestamp = datetime.now().strftime("%I:%M %p")
            
            # Add joke to list with metadata
            joke_with_meta = {
                "text": joke_text,
                "category": category,
                "time": timestamp,
                "id": joke_data.get("id", "")
            }
            
            self.signal_bridge.add_joke.emit(joke_with_meta)
            
            # Show notification
            notification_message = joke_text
            if joke_data["type"] == "twopart":
                notification_message = joke_data['delivery']
                
            self.show_notification(notification_title, notification_message)
            
            # Update status
            self.signal_bridge.update_status.emit(f"Last joke sent successfully at {timestamp}")
            
        except Exception as e:
            self.signal_bridge.update_status.emit(f"Error: {str(e)}")
    
    def show_notification(self, title, message):
        try:
            # Get notification duration from settings
            duration = self.settings.get("notification_duration", 10)
            
            # Use the appropriate notification system
            if NOTIFICATION_SYSTEM == "win10toast_click":
                # This has better Windows support
                toaster.show_toast(
                    title,
                    message,
                    icon_path=None,  # You can specify an icon path here
                    duration=duration,
                    threaded=True
                )
                return True
            elif NOTIFICATION_SYSTEM == "win10toast":
                toaster.show_toast(
                    title,
                    message,
                    duration=duration,
                    threaded=True
                )
                return True
            elif NOTIFICATION_SYSTEM == "plyer":
                notification.notify(
                    title=title,
                    message=message,
                    app_name="Joke Notifier",
                    timeout=duration,
                    app_icon=None  # You can specify an icon path here
                )
                return True
            elif NOTIFICATION_SYSTEM == "notify2":
                n = notify2.Notification(title, message)
                n.timeout = duration * 1000  # Convert to milliseconds
                n.show()
                return True
            elif NOTIFICATION_SYSTEM == "qt":
                # Use Qt's own notification system via QSystemTrayIcon
                if hasattr(self, 'tray_icon'):
                    # Show the notification using Qt's system
                    self.tray_icon.showMessage(
                        title,
                        message,
                        QSystemTrayIcon.MessageIcon.Information,
                        duration * 1000  # milliseconds
                    )
                    return True
                
            # Last resort fallback to a simple messagebox if no notification system is available
            QTimer.singleShot(0, lambda: QMessageBox.information(self, title, message))
            return True
                
        except Exception as e:
            self.signal_bridge.update_status.emit(f"Notification error: {str(e)}")
            
            # If all else fails, use Qt's message box as a last resort
            try:
                QTimer.singleShot(0, lambda: QMessageBox.information(self, title, message))
            except:
                pass
                
            return False
    
    def send_test_notification(self):
        self.show_notification(
            "Test Notification", 
            "This is a test notification from Joke Notifier. If you can see this, notifications are working!"
        )
        self.status_label.setText("Test notification sent")
    
    def add_joke_to_list(self, joke_data):
        # Add to the start of the list
        self.last_jokes.insert(0, joke_data)
        
        # Keep only the last max_stored_jokes
        if len(self.last_jokes) > self.max_stored_jokes:
            self.last_jokes = self.last_jokes[:self.max_stored_jokes]
        
        # Update the listbox
        self.update_jokes_listbox()
    
    def update_jokes_listbox(self):
        # Clear the listbox
        self.jokes_listbox.clear()
        
        # Add jokes to the listbox
        for joke in self.last_jokes:
            # Format the joke to fit in the listbox
            joke_text = joke["text"].replace('\n\n', ' - ')
            if len(joke_text) > 60:
                joke_text = joke_text[:57] + "..."
            
            display_text = f"[{joke['time']}] {joke_text}"
            self.jokes_listbox.addItem(display_text)
    
    def show_full_joke(self, item):
        # Get selected index
        index = self.jokes_listbox.row(item)
        joke = self.last_jokes[index]
        
        # Create a dialog to show the joke
        joke_dialog = QDialog(self)
        joke_dialog.setWindowTitle("Joke Detail")
        joke_dialog.setMinimumSize(400, 300)
        joke_dialog.setModal(True)
        
        # Create layout
        layout = QVBoxLayout(joke_dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Category and time
        info_layout = QHBoxLayout()
        
        category_label = QLabel(f"Category: {joke['category']}")
        category_label.setStyleSheet("font-style: italic;")
        info_layout.addWidget(category_label)
        
        info_layout.addStretch()
        
        time_label = QLabel(f"Time: {joke['time']}")
        time_label.setStyleSheet("font-style: italic;")
        info_layout.addWidget(time_label)
        
        layout.addLayout(info_layout)
        
        # Joke text
        joke_text_edit = QTextEdit()
        joke_text_edit.setReadOnly(True)
        joke_text_edit.setPlainText(joke["text"])
        joke_text_edit.setFont(QFont("Arial", 12))
        layout.addWidget(joke_text_edit)
        
        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(joke_dialog.accept)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignCenter)
        
        # Show dialog
        joke_dialog.exec()
    
    def update_status(self, message):
        self.status_label.setText(message)
    
    def open_settings(self):
        # Create settings dialog
        settings_dialog = SettingsDialog(self.settings, self)
        
        # Connect the save signal
        if settings_dialog.exec():
            # Update settings
            if settings_dialog.result() == QDialog.DialogCode.Accepted:
                new_settings = settings_dialog.get_settings()
                
                # Check if settings have changed
                was_running = self.is_running
                settings_changed = (
                    self.settings.get("frequency") != new_settings.get("frequency") or
                    self.settings.get("categories") != new_settings.get("categories") or
                    self.settings.get("safe_mode") != new_settings.get("safe_mode") or
                    self.settings.get("joke_type") != new_settings.get("joke_type") or
                    self.settings.get("language") != new_settings.get("language") or
                    self.settings.get("autostart", False) != new_settings.get("autostart")
                )
                
                # Update settings
                self.settings = new_settings
                
                # Update max stored jokes
                self.max_stored_jokes = self.settings.get("max_history", 15)
                
                # Apply any changes that need immediate action
                if was_running and settings_changed:
                    # Restart notifications to apply new settings
                    self.stop_notifications()
                    self.start_notifications()
                
                # Save settings to file
                self.save_settings_to_file()
                
                # Show confirmation
                self.status_label.setText("Settings saved successfully")
    
    def save_settings_to_file(self):
        # Save settings to a JSON file
        try:
            settings_dir = os.path.dirname(os.path.abspath(__file__))
            settings_path = os.path.join(settings_dir, "joke_notifier_settings.json")
            
            with open(settings_path, "w") as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            self.status_label.setText(f"Error saving settings: {str(e)}")
    
    def load_settings(self):
        # Load settings from a JSON file
        try:
            settings_dir = os.path.dirname(os.path.abspath(__file__))
            settings_path = os.path.join(settings_dir, "joke_notifier_settings.json")
            
            if os.path.exists(settings_path):
                with open(settings_path, "r") as f:
                    loaded_settings = json.load(f)
                    self.settings.update(loaded_settings)
        except Exception as e:
            self.status_label.setText(f"Error loading settings: {str(e)}")
    
    def closeEvent(self, event):
        if hasattr(self, 'tray_icon') and self.tray_icon.isVisible():
            # Show a balloon message when minimizing to tray for the first time
            QTimer.singleShot(500, lambda: self.tray_icon.showMessage(
                "Joke Notifier",
                "Joke Notifier is still running in the system tray. Right-click the icon for options.",
                QSystemTrayIcon.MessageIcon.Information,
                3000
            ))
            
            # Hide the window instead of closing
            self.hide()
            event.ignore()
        else:
            # Stop the notifications if running
            if self.is_running:
                self.stop_notifications()
            
            # Save settings
            self.save_settings_to_file()
            
            # Accept the close event
            event.accept()


class SettingsDialog(QDialog):
    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Joke Notifier Settings")
        self.setMinimumSize(500, 600)
        self.setModal(True)
        
        # Store reference to current settings
        self.current_settings = current_settings
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        
        # Title
        title_label = QLabel("Joke Notifier Settings")
        title_label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)
        
        # Scroll area for settings
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        main_layout.addWidget(scroll_area)
        
        # Container for settings
        settings_widget = QWidget()
        scroll_area.setWidget(settings_widget)
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.setContentsMargins(5, 5, 5, 5)
        settings_layout.setSpacing(15)
        
        # ========== Frequency settings ==========
        frequency_group = QGroupBox("Notification Frequency")
        frequency_layout = QVBoxLayout(frequency_group)
        
        self.frequency_label = QLabel(f"Show a joke every {current_settings['frequency']} minutes")
        frequency_layout.addWidget(self.frequency_label)
        
        # Frequency slider
        self.frequency_slider = QSlider(Qt.Orientation.Horizontal)
        self.frequency_slider.setMinimum(1)
        self.frequency_slider.setMaximum(120)
        self.frequency_slider.setValue(current_settings["frequency"])
        self.frequency_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.frequency_slider.setTickInterval(10)
        self.frequency_slider.valueChanged.connect(self.update_frequency_display)
        frequency_layout.addWidget(self.frequency_slider)
        
        # Quick select buttons
        quick_select_layout = QHBoxLayout()
        quick_select_layout.addWidget(QLabel("Quick select:"))
        
        for minutes in [5, 15, 30, 60]:
            quick_btn = QPushButton(f"{minutes}m")
            quick_btn.setFixedWidth(50)
            quick_btn.clicked.connect(lambda checked, m=minutes: self.set_quick_time(m))
            quick_select_layout.addWidget(quick_btn)
        
        frequency_layout.addLayout(quick_select_layout)
        settings_layout.addWidget(frequency_group)
        
        # ========== Category settings ==========
        category_group = QGroupBox("Joke Categories")
        category_layout = QVBoxLayout(category_group)
        
        # Category mode selection
        self.category_mode_any = QRadioButton("Any Category (Random selection)")
        self.category_mode_any.setChecked("Any" in current_settings["categories"])
        category_layout.addWidget(self.category_mode_any)
        
        self.category_mode_specific = QRadioButton("Specific Categories:")
        self.category_mode_specific.setChecked("Any" not in current_settings["categories"])
        category_layout.addWidget(self.category_mode_specific)
        
        # Connect signals to enable/disable checkboxes
        self.category_mode_any.toggled.connect(self.update_category_mode)
        
        # Categories frame
        categories_frame = QFrame()
        categories_frame.setContentsMargins(20, 0, 0, 0)
        category_layout.addWidget(categories_frame)
        
        # Grid layout for checkboxes
        categories_grid = QGridLayout(categories_frame)
        categories_grid.setContentsMargins(0, 0, 0, 0)
        
        # Available categories
        available_categories = [
            "Misc", "Programming", "Dark", "Pun", "Spooky", "Christmas"
        ]
        
        # Create checkboxes
        self.category_checkboxes = {}
        row, col = 0, 0
        for i, cat in enumerate(available_categories):
            checkbox = QCheckBox(cat)
            checkbox.setChecked(cat in current_settings["categories"] and "Any" not in current_settings["categories"])
            self.category_checkboxes[cat] = checkbox
            
            # Arrange in 2 columns
            categories_grid.addWidget(checkbox, row, col)
            row += 1
            if row > len(available_categories) // 2:
                row = 0
                col += 1
        
        # Initial checkbox state
        self.update_category_mode()
        
        settings_layout.addWidget(category_group)
        
        # ========== Content filter settings ==========
        filter_group = QGroupBox("Content Filter")
        filter_layout = QVBoxLayout(filter_group)
        
        self.safe_mode_cb = QCheckBox("Safe Mode (Filter potentially offensive jokes)")
        self.safe_mode_cb.setChecked(current_settings["safe_mode"])
        filter_layout.addWidget(self.safe_mode_cb)
        
        blacklist_note = QLabel("Note: Religious, racist, sexist and explicit jokes are\nalways blacklisted for your comfort.")
        blacklist_note.setStyleSheet("color: gray; font-style: italic;")
        filter_layout.addWidget(blacklist_note)
        
        settings_layout.addWidget(filter_group)
        
        # ========== Joke type settings ==========
        type_group = QGroupBox("Joke Type")
        type_layout = QVBoxLayout(type_group)
        
        self.joke_type_any = QRadioButton("Any Type")
        self.joke_type_any.setChecked(current_settings["joke_type"] == "Any")
        type_layout.addWidget(self.joke_type_any)
        
        self.joke_type_single = QRadioButton("Single (One-liner)")
        self.joke_type_single.setChecked(current_settings["joke_type"] == "single")
        type_layout.addWidget(self.joke_type_single)
        
        self.joke_type_twopart = QRadioButton("Two Part (Setup + Punchline)")
        self.joke_type_twopart.setChecked(current_settings["joke_type"] == "twopart")
        type_layout.addWidget(self.joke_type_twopart)
        
        settings_layout.addWidget(type_group)
        
        # ========== Language settings ==========
        language_group = QGroupBox("Language")
        language_layout = QVBoxLayout(language_group)
        
        # Available languages
        languages = [
            ("English", "en"),
            ("German", "de"),
            ("Spanish", "es"),
            ("French", "fr"),
            ("Italian", "it")
        ]
        
        # Create language radio buttons
        self.language_buttons = {}
        for lang_name, lang_code in languages:
            radio = QRadioButton(lang_name)
            radio.setChecked(current_settings["language"] == lang_code)
            self.language_buttons[lang_code] = radio
            language_layout.addWidget(radio)
        
        settings_layout.addWidget(language_group)
        
        # ========== Advanced options ==========
        advanced_group = QGroupBox("Advanced Options")
        advanced_layout = QVBoxLayout(advanced_group)
        
        self.autostart_cb = QCheckBox("Start notifications automatically when app launches")
        self.autostart_cb.setChecked(current_settings.get("autostart", False))
        advanced_layout.addWidget(self.autostart_cb)
        
        settings_layout.addWidget(advanced_group)
        
        # ========== Buttons ==========
        buttons_layout = QHBoxLayout()
        
        # Status message
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: green; font-style: italic;")
        buttons_layout.addWidget(self.status_label, 1)
        
        # Cancel button
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)
        
        # Save button
        save_button = QPushButton("Save Settings")
        save_button.clicked.connect(self.accept)
        save_button.setStyleSheet("font-weight: bold;")
        buttons_layout.addWidget(save_button)
        
        main_layout.addLayout(buttons_layout)
    
    def update_frequency_display(self, value):
        self.frequency_label.setText(f"Show a joke every {value} minutes")
    
    def set_quick_time(self, minutes):
        self.frequency_slider.setValue(minutes)
        self.update_frequency_display(minutes)
    
    def update_category_mode(self):
        enabled = not self.category_mode_any.isChecked()
        
        for checkbox in self.category_checkboxes.values():
            checkbox.setEnabled(enabled)
    
    def get_settings(self):
        # Build settings dictionary from UI state
        settings = dict(self.current_settings)  # Start with a copy of current settings
        
        # Frequency
        settings["frequency"] = self.frequency_slider.value()
        
        # Categories
        if self.category_mode_any.isChecked():
            settings["categories"] = ["Any"]
        else:
            selected_categories = [cat for cat, cb in self.category_checkboxes.items() if cb.isChecked()]
            
            # Ensure at least one category is selected
            if not selected_categories:
                selected_categories = ["Misc"]  # Default to Misc if nothing selected
            
            settings["categories"] = selected_categories
        
        # Safe mode
        settings["safe_mode"] = self.safe_mode_cb.isChecked()
        
        # Joke type
        if self.joke_type_any.isChecked():
            settings["joke_type"] = "Any"
        elif self.joke_type_single.isChecked():
            settings["joke_type"] = "single"
        else:
            settings["joke_type"] = "twopart"
        
        # Language
        for lang_code, radio in self.language_buttons.items():
            if radio.isChecked():
                settings["language"] = lang_code
                break
        
        # Advanced options
        settings["autostart"] = self.autostart_cb.isChecked()
        
        return settings


def apply_dark_theme(app):
    # Dark color palette
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
    dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(25, 25, 25))
    dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    
    # Apply the palette
    app.setPalette(dark_palette)
    
    # Set stylesheet for additional customizations
    app.setStyleSheet("""
        QGroupBox {
            font-weight: bold;
            border: 1px solid #555;
            border-radius: 5px;
            margin-top: 10px;
            padding-top: 10px;
        }
        
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
        }
        
        QPushButton {
            padding: 6px 12px;
            border-radius: 3px;
            background-color: #444;
            color: white;
            border: 1px solid #555;
        }
        
        QPushButton:hover {
            background-color: #555;
        }
        
        QPushButton:pressed {
            background-color: #333;
        }
        
        QLabel {
            color: white;
        }
        
        QListWidget {
            background-color: #333;
            color: white;
            alternate-background-color: #3a3a3a;
            border: 1px solid #555;
        }
        
        QSlider::groove:horizontal {
            height: 8px;
            background: #444;
            border-radius: 4px;
        }
        
        QSlider::handle:horizontal {
            background: #2a82da;
            border: 1px solid #2a82da;
            width: 18px;
            margin: -6px 0;
            border-radius: 9px;
        }
        
        QSlider::add-page:horizontal {
            background: #444;
            border-radius: 4px;
        }
        
        QSlider::sub-page:horizontal {
            background: #2a82da;
            border-radius: 4px;
        }
        
        QCheckBox {
            color: white;
        }
        
        QRadioButton {
            color: white;
        }
        
        QScrollArea {
            background-color: #333;
            border: none;
        }
        
        QTextEdit {
            background-color: #333;
            color: white;
            border: 1px solid #555;
        }
    """)


def apply_light_theme(app):
    # Set application-wide font
    app.setFont(QFont("Arial", 10))
    
    # Apply stylesheet for better appearance
    app.setStyleSheet("""
        QGroupBox {
            font-weight: bold;
            border: 1px solid #ccc;
            border-radius: 5px;
            margin-top: 10px;
            padding-top: 10px;
        }
        
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
        }
        
        QPushButton {
            padding: 6px 12px;
            border-radius: 3px;
            background-color: #f0f0f0;
        }
        
        QPushButton:hover {
            background-color: #e0e0e0;
        }
        
        QPushButton:pressed {
            background-color: #d0d0d0;
        }
        
        QSlider::groove:horizontal {
            height: 8px;
            background: #ddd;
            border-radius: 4px;
        }
        
        QSlider::handle:horizontal {
            background: #5c9eff;
            border: 1px solid #5c9eff;
            width: 18px;
            margin: -6px 0;
            border-radius: 9px;
        }
        
        QSlider::add-page:horizontal {
            background: #ddd;
            border-radius: 4px;
        }
        
        QSlider::sub-page:horizontal {
            background: #9fc7ff;
            border-radius: 4px;
        }
    """)


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Use Fusion style for a modern look
    
    # Detect system theme (you might need to customize this for your needs)
    # This is a basic approach - a more sophisticated detection might be needed
    is_dark_theme = False
    
    # Check if Windows is using dark theme
    if sys.platform == 'win32':
        try:
            import winreg
            registry = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
            key = winreg.OpenKey(registry, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize')
            value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
            is_dark_theme = value == 0
        except:
            # If we can't determine, assume light theme
            pass
    
    # Apply appropriate theme
    if is_dark_theme:
        apply_dark_theme(app)
    else:
        apply_light_theme(app)
    
    window = JokeNotifier()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()