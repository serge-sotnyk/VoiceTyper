import asyncio
import codecs
import json
import os
import threading
import time
import wave
from datetime import datetime

import customtkinter as ctk
import pyaudio
import pystray
from PIL import Image
from deepgram import Deepgram
from deepgram.errors import DeepgramSetupError
from playsound import playsound
from pynput import keyboard

# Set theme and color scheme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class SettingsDialog:
    def __init__(self, parent, callback=None):
        self.dialog = ctk.CTkToplevel(parent)
        self.dialog.title("Settings")
        self.dialog.geometry("400x320")  # Increased height for new shortcut options
        self.dialog.transient(parent)
        self.dialog.resizable(False, False)

        # Store reference to callback function
        self.callback = callback

        # Load current settings
        with open('settings.json', 'r') as f:
            self.settings = json.load(f)

        # API Key input
        self.api_frame = ctk.CTkFrame(self.dialog)
        self.api_frame.pack(fill="x", padx=20, pady=10)

        self.api_label = ctk.CTkLabel(
            self.api_frame,
            text="Deepgram API Key:",
            font=ctk.CTkFont(size=14)
        )
        self.api_label.pack(anchor="w", pady=5)

        self.api_entry = ctk.CTkEntry(
            self.api_frame,
            width=300,
            font=ctk.CTkFont(size=14)
        )
        self.api_entry.pack(pady=5)
        self.api_entry.insert(0, self.settings.get('api_key', ''))

        # Keyboard shortcut options
        self.shortcut_frame = ctk.CTkFrame(self.dialog)
        self.shortcut_frame.pack(fill="x", padx=20, pady=10)

        self.shortcut_label = ctk.CTkLabel(
            self.shortcut_frame,
            text="Recording Keyboard Shortcut:",
            font=ctk.CTkFont(size=14)
        )
        self.shortcut_label.pack(anchor="w", pady=5)

        # Get current shortcut or default to F2
        current_shortcut = self.settings.get('shortcut', 'f2')
        
        # Define available shortcuts
        self.shortcuts = {
            'f2': 'F2',
            'alt+f2': 'Alt+F2',
            'ctrl+f12': 'Ctrl+F12',
            'alt+f12': 'Alt+F12'
        }
        
        # Radio buttons for shortcuts
        self.shortcut_var = ctk.StringVar(value=current_shortcut)
        
        for key, label in self.shortcuts.items():
            shortcut_radio = ctk.CTkRadioButton(
                self.shortcut_frame,
                text=label,
                variable=self.shortcut_var,
                value=key,
                font=ctk.CTkFont(size=12)
            )
            shortcut_radio.pack(anchor="w", padx=20, pady=2)

        # Save button
        self.save_btn = ctk.CTkButton(
            self.dialog,
            text="Save",
            command=self.save_settings,
            width=100
        )
        self.save_btn.pack(pady=15)

    def save_settings(self):
        self.settings['api_key'] = self.api_entry.get()
        self.settings['shortcut'] = self.shortcut_var.get()
        with open('settings.json', 'w') as f:
            json.dump(self.settings, f)
        
        # Execute callback if provided to update UI
        if self.callback:
            self.callback()
            
        self.dialog.destroy()


class VoiceTyperApp:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("Voice Typer Pro")
        self.root.geometry("400x250")
        self.root.minsize(400, 250)

        # Initialize variables
        self.is_recording = False
        self.file_ready_counter = 0
        self.stop_recording = False
        self.pykeyboard = keyboard.Controller()
        self.recording_animation_active = False
        
        # Initialize hotkey related variables
        self.hotkey_listener = None  # Store the hotkey listener
        
        # Flag for proper thread termination
        self.running = True

        # Try to load settings and initialize Deepgram
        try:
            self.load_settings()
        except DeepgramSetupError:
            # Show settings dialog immediately if API key is invalid
            self.setup_ui()  # Setup UI first
            self.show_api_key_error()
        except Exception as e:
            self.setup_ui()
            self.show_error(f"Error: {str(e)}")

        # Initialize system tray
        self.setup_system_tray()

        # Track if log section is expanded
        self.log_expanded = False  # Start with log collapsed

        self.setup_ui()
        self.setup_hotkey()  # Set up hotkey after loading settings
        self.start_transcription_thread()

        # Add window close event handler
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)

    def show_api_key_error(self):
        error_dialog = ctk.CTkToplevel(self.root)
        error_dialog.title("API Key Error")
        error_dialog.geometry("400x200")
        error_dialog.transient(self.root)
        error_dialog.resizable(False, False)

        # Center the dialog
        error_dialog.geometry("+%d+%d" % (
            self.root.winfo_x() + (self.root.winfo_width() - 400) // 2,
            self.root.winfo_y() + (self.root.winfo_height() - 200) // 2
        ))

        # Error message
        message = ctk.CTkLabel(
            error_dialog,
            text="Invalid Deepgram API Key detected.\nPlease enter a valid API key to continue.",
            font=ctk.CTkFont(size=14),
            wraplength=350
        )
        message.pack(pady=20)

        # API Key input
        api_entry = ctk.CTkEntry(
            error_dialog,
            width=300,
            font=ctk.CTkFont(size=14)
        )
        api_entry.pack(pady=10)
        api_entry.insert(0, self.settings.get('api_key', ''))

        def save_and_retry():
            new_key = api_entry.get()
            try:
                # Try to initialize Deepgram with new key
                self.deepgram = Deepgram(new_key)
                # If successful, save the new key
                self.settings['api_key'] = new_key
                with open('settings.json', 'w') as f:
                    json.dump(self.settings, f)
                error_dialog.destroy()
                self.status_label.configure(text="API Key updated successfully!")
            except DeepgramSetupError:
                message.configure(text="Invalid API Key. Please try again.", text_color="red")

        # Save button
        save_btn = ctk.CTkButton(
            error_dialog,
            text="Save & Retry",
            command=save_and_retry,
            width=120
        )
        save_btn.pack(pady=20)

    def show_error(self, error_message):
        self.status_label.configure(
            text=error_message,
            text_color="red"
        )

    def load_settings(self):
        try:
            with open('settings.json', 'r') as f:
                self.settings = json.load(f)
            # Ensure shortcut is set, default to 'f2' if not
            if 'shortcut' not in self.settings:
                self.settings['shortcut'] = 'f2'
                with open('settings.json', 'w') as f:
                    json.dump(self.settings, f)
        except FileNotFoundError:
            self.settings = {'api_key': '', 'shortcut': 'f2'}
            with open('settings.json', 'w') as f:
                json.dump(self.settings, f)

        try:
            self.deepgram = Deepgram(self.settings['api_key'])
        except DeepgramSetupError:
            raise
        except Exception as e:
            raise Exception(f"Failed to initialize Deepgram: {str(e)}")

    def setup_system_tray(self):
        # Create system tray icon
        self.icon_image = Image.new('RGB', (64, 64), color='blue')
        self.tray_icon = pystray.Icon(
            "Voice Typer",
            self.icon_image,
            menu=pystray.Menu(
                pystray.MenuItem("Show", self.show_window),
                pystray.MenuItem("Exit", self.quit_app)
            )
        )

    def setup_ui(self):
        # Main container with padding
        self.main_frame = ctk.CTkFrame(self.root)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Header frame with title and settings button
        self.header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.header_frame.pack(fill="x", pady=5)

        # Title
        self.title_label = ctk.CTkLabel(
            self.header_frame,
            text="Voice Typer Pro",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.title_label.pack(side="left", padx=10)

        # Settings button
        self.settings_btn = ctk.CTkButton(
            self.header_frame,
            text="⚙️",
            width=40,
            command=self.open_settings
        )
        self.settings_btn.pack(side="right", padx=10)

        # Record button and indicator in one frame
        self.control_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.control_frame.pack(fill="x", pady=10)

        # Get the current shortcut display text
        shortcut_key = self.settings.get('shortcut', 'f2')
        shortcut_display = self.get_shortcut_display(shortcut_key)
        
        self.record_button = ctk.CTkButton(
            self.control_frame,
            text=f"Start Recording ({shortcut_display})",
            command=self.toggle_recording,
            height=40,
            corner_radius=20
        )
        self.record_button.pack(pady=5)

        self.recording_indicator = ctk.CTkProgressBar(
            self.control_frame,
            width=200,
            height=6
        )
        self.recording_indicator.pack(pady=5)
        self.recording_indicator.set(0)

        # Status label
        self.status_label = ctk.CTkLabel(
            self.main_frame,
            text="Ready to record...",
            font=ctk.CTkFont(size=12)
        )
        self.status_label.pack(pady=5)

        # Create a container frame for log section
        self.log_container = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.log_container.pack(fill="x", expand=False)

        # Log controls in container
        self.toggle_log_btn = ctk.CTkButton(
            self.log_container,
            text="▶ Show Log",
            command=self.toggle_log_section,
            width=100,
            height=28,
            fg_color=["#2B2B2B", "#333333"],
            hover_color=["#333333", "#404040"]
        )
        self.toggle_log_btn.pack(side="left", padx=5)

        self.clear_log_btn = ctk.CTkButton(
            self.log_container,
            text="Clear",
            command=self.clear_logs,
            width=60,
            height=28,
            fg_color="#c93434",
            hover_color="#a82a2a"
        )
        self.clear_log_btn.pack(side="right", padx=5)

        # Log frame and content
        self.log_frame = ctk.CTkFrame(self.main_frame)
        self.transcription_text = ctk.CTkTextbox(
            self.log_frame,
            height=200,
            font=ctk.CTkFont(size=12)
        )
        self.transcription_text.pack(fill="both", expand=True, pady=5)

    def animate_recording(self):
        if self.recording_animation_active:
            current = self.recording_indicator.get()
            if current >= 1:
                self.recording_indicator.set(0)
            else:
                self.recording_indicator.set(current + 0.05)  # Smoother animation
            self.root.after(50, self.animate_recording)  # Faster updates

            # Pulse effect on record button
            current_color = self.record_button.cget("fg_color")
            if current_color == "#c93434":
                self.record_button.configure(fg_color="#a82a2a")
            else:
                self.record_button.configure(fg_color="#c93434")

    def toggle_recording(self):
        if not hasattr(self, 'deepgram'):
            self.show_api_key_error()
            return

        # Get the current shortcut display text
        shortcut_key = self.settings.get('shortcut', 'f2')
        shortcut_display = self.get_shortcut_display(shortcut_key)
        
        if not self.is_recording:
            self.start_recording()
            # Start animation with pulsing effect
            self.recording_animation_active = True
            self.record_button.configure(
                fg_color="#c93434",
                text=f"■ Stop Recording ({shortcut_display})"
            )
            self.animate_recording()
        else:
            self.stop_recording = True
            # Stop animation
            self.recording_animation_active = False
            self.record_button.configure(
                fg_color=["#3B8ED0", "#1F6AA5"],
                text=f"● Start Recording ({shortcut_display})"
            )
            self.recording_indicator.set(0)

    def setup_hotkey(self):
        """Sets up the hotkey based on current settings."""
        # If a hotkey listener already exists, stop it
        if hasattr(self, 'hotkey_listener') and self.hotkey_listener:
            self.hotkey_listener.stop()
            
        # Get configured shortcut
        shortcut = self.settings.get('shortcut', 'f2')
        
        # Map virtual key codes for function keys
        # F2 = 113, F12 = 123
        hotkey_map = {}
        
        # Define hotkey based on settings
        if shortcut == 'f2':
            hotkey_map['<113>'] = self.toggle_recording  # F2 key
        elif shortcut == 'alt+f2':
            hotkey_map['<alt>+<113>'] = self.toggle_recording  # Alt + F2
        elif shortcut == 'ctrl+f12':
            hotkey_map['<ctrl>+<123>'] = self.toggle_recording  # Ctrl + F12
        elif shortcut == 'alt+f12':
            hotkey_map['<alt>+<123>'] = self.toggle_recording  # Alt + F12
            
        # Create a new GlobalHotKeys listener
        self.hotkey_listener = keyboard.GlobalHotKeys(hotkey_map)
        
        # Start the listener
        self.hotkey_listener.start()

    def start_recording(self):
        threading.Thread(target=self.record_speech, daemon=True).start()

    def record_speech(self):
        self.is_recording = True
        chunk = 1024
        sample_format = pyaudio.paInt16
        channels = 2
        fs = 44100

        p = pyaudio.PyAudio()
        stream = p.open(
            format=sample_format,
            channels=channels,
            rate=fs,
            frames_per_buffer=chunk,
            input=True
        )

        frames = []
        playsound("assets/on.wav")

        while not self.stop_recording:
            data = stream.read(chunk)
            frames.append(data)

        stream.stop_stream()
        stream.close()
        p.terminate()
        playsound("assets/off.wav")

        # Save recording
        wf = wave.open(f"test{self.file_ready_counter + 1}.wav", 'wb')
        wf.setnchannels(channels)
        wf.setsampwidth(p.get_sample_size(sample_format))
        wf.setframerate(fs)
        wf.writeframes(b''.join(frames))
        wf.close()

        self.stop_recording = False
        self.is_recording = False
        self.file_ready_counter += 1

        self.status_label.configure(text="Processing transcription...")

    async def transcribe_audio(self, audio_file):
        with open(audio_file, 'rb') as audio:
            source = {'buffer': audio, 'mimetype': 'audio/wav'}
            options = {
                'punctuate': True,
                # 'language': 'en',
                'detect_language': True,
                # 'model': 'general',
                'model': 'nova-3'
            }
            response = await self.deepgram.transcription.prerecorded(source, options)
            return response['results']['channels'][0]['alternatives'][0]['transcript']

    def start_transcription_thread(self):
        threading.Thread(target=self.transcribe_speech).start()

    def transcribe_speech(self):
        i = 1

        while self.running:
            while self.file_ready_counter < i and self.running:
                time.sleep(0.01)

            if not self.running:
                break

            audio_file = f"test{i}.wav"
            try:
                transcript = asyncio.run(self.transcribe_audio(audio_file))

                # Update GUI
                self.transcription_text.insert('1.0', f"{datetime.now().strftime('%H:%M:%S')}: {transcript}\n\n")
                self.status_label.configure(text="Ready to record...")

                # Log transcription
                with codecs.open('transcribe.log', 'a', encoding='utf-8') as f:
                    f.write(f"{datetime.now()}: {transcript}\n")

                # Type the text
                for element in transcript:
                    try:
                        self.pykeyboard.type(element)
                        time.sleep(0.0025)
                    except:
                        print("empty or unknown symbol")

                os.remove(audio_file)
                i += 1

            except Exception as e:
                self.status_label.configure(text=f"Error: {str(e)}")
                i += 1

    def __del__(self):
        # Clean up hotkey listener
        if hasattr(self, 'hotkey_listener'):
            self.hotkey_listener.stop()

    def toggle_log_section(self):
        current_height = self.root.winfo_height()
        
        if not self.log_expanded:
            # Show log section
            self.log_frame.pack(fill="both", expand=True, padx=5, pady=5)
            self.toggle_log_btn.configure(text="▼ Hide Log")
            # Immediately resize window
            target_height = current_height + 200
            self.root.geometry(f"400x{target_height}")
            self.log_expanded = True
        else:
            # Hide log section
            target_height = current_height - 200
            self.root.geometry(f"400x{target_height}")
            self.log_frame.pack_forget()
            self.toggle_log_btn.configure(text="▶ Show Log")
            self.log_expanded = False

    def clear_logs(self):
        self.transcription_text.delete('1.0', 'end')
        # Also clear the log file
        with open('transcribe.log', 'w', encoding='utf-8') as f:
            f.write('')

    def minimize_to_tray(self):
        self.root.withdraw()  # Hide the window
        if not self.tray_icon.visible:
            # Start system tray icon in a separate thread
            threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_window(self):
        self.tray_icon.stop()
        self.root.after(0, self.root.deiconify)

    def quit_app(self):
        # Stop background threads
        self.running = False

        # Stop hotkey listener
        if hasattr(self, 'hotkey_listener') and self.hotkey_listener:
            self.hotkey_listener.stop()

        # Stop system tray icon
        if hasattr(self, 'tray_icon') and self.tray_icon.visible:
            self.tray_icon.stop()

        # Close main window
        self.root.quit()
        self.root.destroy()  # Explicitly destroy the window

    def open_settings(self):
        # Pass the update_ui_on_settings_change callback to refresh UI after settings change
        SettingsDialog(self.root, callback=self.update_ui_on_settings_change)
        
    def update_ui_on_settings_change(self):
        # Reload settings from file
        with open('settings.json', 'r') as f:
            self.settings = json.load(f)
            
        # Update button text with current shortcut
        shortcut_key = self.settings.get('shortcut', 'f2')
        shortcut_display = self.get_shortcut_display(shortcut_key)
        
        # Update button text based on recording state
        if self.is_recording:
            self.record_button.configure(
                text=f"■ Stop Recording ({shortcut_display})"
            )
        else:
            self.record_button.configure(
                text=f"● Start Recording ({shortcut_display})"
            )
            
        # Update hotkey configuration
        self.setup_hotkey()
        
    def get_shortcut_display(self, shortcut_key):
        # Get prettier display format for shortcuts
        shortcuts_display = {
            'f2': 'F2',
            'alt+f2': 'Alt+F2',
            'ctrl+f12': 'Ctrl+F12',
            'alt+f12': 'Alt+F12'
        }
        return shortcuts_display.get(shortcut_key, shortcut_key.upper())

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = VoiceTyperApp()
    app.run()
