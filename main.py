import tkinter as tk
from tkinter import messagebox, simpledialog
import re
import os
import json
from weasyprint import HTML
import zipfile
import uuid
from datetime import datetime
import threading


class OutputWrapper:
    MAX_COLUMNS = 6
    def __init__(self, app, parent_frame, font_settings):
        self.app = app
        self.parent = parent_frame
        self.font_settings = font_settings
        self.columns = []

        # Central storage for column behavior
        self.column_mode = "auto"  # "one", "two" (Multi), or "auto"
        self.forced_multi_count = 2  # Default number for Multi mode
        # Dictionary to store theme colors and tag definitions centrally
        self.current_theme = {
            "bg": "#1e1e1e",
            "fg": "white",
            "chord": "#ffcc00",
            "comment": "#64B5F6",
            "alt": "#98c379"
        }

        # Store event bindings to re-apply them after a rebuild
        self.registered_bindings = []

        self.rebuild(1)

    def set_column_mode(self, mode):
        """
        Central entry point to change layout mode (one/two/auto).
        """
        valid_modes = ["one", "two", "auto"]
        if mode in valid_modes:
            self.column_mode = mode
            self.app.render_view()

    def get_target_column_count(self, lines):
        """
        Logic to determine how many columns to build.
        Uses forced_multi_count when in 'two' (Multi) mode.
        """
        # 1. Force single column
        if self.column_mode == "one":
            return 1

        # 2. Use user-defined count for Multi-column mode
        if self.column_mode == "two":
            # Use the value we set via the COLS + / - buttons
            return self.forced_multi_count

        # 3. Fallback to auto-calculation logic (the "auto" mode)
        pixel_width = self.parent.winfo_width()
        if pixel_width < 100: return 1

        char_width = self.app.font_size * 0.75
        max_line_len = max([len(l[0]) for l in lines]) if lines else 0
        fitted_cols = int(pixel_width // (max_line_len * char_width + 20))
        return max(1, min(self.MAX_COLUMNS, fitted_cols)) # Increased limit to 6

    def sync_yview(self, *args):
        """
        Only sync yview manually when NOT auto-scrolling.
        During auto-scroll, PerformanceManager handles the logic.
        """
        # Access the performance manager's state
        # Assuming 'perf_manager' is accessible via the app/root
        if hasattr(self.app, 'perf_manager') and self.app.perf_manager.is_scrolling:
            # In multi-column mode, we only want the master to scroll pixels
            # The slaves are updated via rendering, so we skip the physical yview sync.
            if len(self.columns) > 1:
                self.columns[0].yview(*args)
                return

        # Default behavior for single column or manual scrolling
        for col in self.columns:
            try:
                col.yview(*args)
            except tk.TclError:
                pass

    def on_scroll_event(self, *args):
        """
        Keep the scrollbar updated, but avoid heavy logic during auto-scroll.
        """
        try:
            if hasattr(self, 'scrollbar') and self.columns:
                self.scrollbar.set(*self.columns[0].yview())

                # If auto-scrolling in multi-column, 
                # we might want to trigger the slave-render here if not done in run_scroll.
                # But usually, keeping this simple is better for performance.
        except (tk.TclError, IndexError):
            pass

    def apply_layout_params(self, theme, font_size=None):
        """
        Updates internal style parameters and refreshes all active columns.
        """
        self.current_theme.update(theme)
        if font_size:
            self.font_settings = ("DejaVu Sans Mono", font_size, "bold")

        # Apply changes to currently existing widgets
        for col in self.columns:
            self._apply_styles_to_widget(col)

    def _apply_styles_to_widget(self, txt):
        """
        Configures colors, fonts, and syntax tags for a specific text widget.
        """
        txt.config(
            bg=self.current_theme["bg"],
            fg=self.current_theme["fg"],
            font=self.font_settings,
            insertbackground=self.current_theme["fg"]
        )

        # Apply Syntax Highlighting Tags
        txt.tag_config("normal", foreground=self.current_theme["fg"])
        txt.tag_config("chord", foreground=self.current_theme["chord"])
        txt.tag_config("comment",
                       foreground=self.current_theme["comment"],
                       font=("Arial", self.app.font_size, "italic"))
        txt.tag_config("alt_move", foreground=self.current_theme.get("alt", "#98c379"))
        txt.tag_config("overlap_red", foreground="#ff4444",
                       font=(self.font_settings[0], self.font_settings[1], "italic"))

        # Ensure chord and comment tags stay on top of the 'normal' tag
        txt.tag_raise("chord")
        txt.tag_raise("comment")
        txt.tag_lower("normal")

    def rebuild(self, n):
        """
        Clears the container and creates N columns.
        Resets grid weights to ensure columns always fill the full width.
        """
        # 1. Destroy old widgets
        for widget in self.parent.winfo_children():
            widget.destroy()
        self.columns = []

        # 2. Reset ALL possible grid weights (up to your max of self.MAX_COLUMNS)
        # This is crucial! It prevents empty columns from taking up space.
        for i in range(self.MAX_COLUMNS + 1): # Reset 0 through 6
            self.parent.grid_columnconfigure(i, weight=0, uniform="")

        # 3. Configure only the active columns
        for i in range(n):
            self.parent.grid_columnconfigure(i, weight=1, uniform="group1")
        self.parent.grid_rowconfigure(0, weight=1)

        for i in range(n):
            txt = tk.Text(
                self.parent,
                wrap=tk.NONE,
                undo=False,
                borderwidth=0,
                highlightthickness=0,
                padx=10,
                # Set a small width so the grid logic
                # forces them to expand equally rather than based on content
                width=1
            )

            self._apply_styles_to_widget(txt)

            for event, handler in self.registered_bindings:
                txt.bind(event, handler)

            # Use grid instead of pack for strict width equality
            txt.grid(row=0, column=i, sticky="nsew")

            # Sync with the scrollbar
            txt.config(yscrollcommand=self.on_scroll_event)

            self.columns.append(txt)

        return self.columns

    # --- Proxy Methods for ChoConverterApp Compatibility ---

    def bind(self, event, handler, add=None):
        """
        Binds an event to all current columns and saves it for future columns.
        """
        # Store the binding so it persists through rebuilds
        self.registered_bindings.append((event, handler))
        for col in self.columns:
            col.bind(event, handler, add=add)

    def configure(self, **kwargs):
        """ Standard widget configuration proxy. """
        if 'font' in kwargs:
            self.font_settings = kwargs['font']
        for col in self.columns:
            col.configure(**kwargs)

    def tag_configure(self, tag_name, **kwargs):
        """ Proxy for tag updates. """
        for col in self.columns:
            col.tag_configure(tag_name, **kwargs)

    def delete(self, start, end):
        for col in self.columns:
            col.config(state=tk.NORMAL)
            col.delete(start, end)

    def insert(self, index, content, tags=None):
        if self.columns:
            self.columns[0].config(state=tk.NORMAL)
            self.columns[0].insert(index, content, tags)

    def yview(self, *args):
        for col in self.columns:
            col.yview(*args)

    def cget(self, option):
        if self.columns:
            return self.columns[0].cget(option)
        return self.current_theme.get(option, "")

CHORD_EXPLANATIONS =    {
# --- Major Chords (Open Positions) ---
            "A": "A major. Fretboard: X-0-2-2-2-0",
            "B": "B major (Barré on 2nd fret). Fretboard: X-2-4-4-4-2",
            "C": "C major. Fretboard: X-3-2-0-1-0",
            "D": "D major. Fretboard: X-X-0-2-3-2",
            "E": "E major. Fretboard: 0-2-2-1-0-0",
            "F": "F major (Full barré). Fretboard: 1-3-3-2-1-1",
            "G": "G major. Fretboard: 3-2-0-0-0-3",

            # --- Minor Chords (Open Positions) ---
            "Am": "A minor. Fretboard: X-0-2-2-1-0",
            "Bm": "B minor (Barré on 2nd fret). Fretboard: X-2-4-4-3-2",
            "Cm": "C minor (Barré on 3rd fret). Fretboard: X-3-5-5-4-3",
            "Dm": "D minor. Fretboard: X-X-0-2-3-1",
            "Em": "E minor. Fretboard: 0-2-2-0-0-0",
            "Fm": "F minor (Full barré). Fretboard: 1-3-3-1-1-1",
            "Gm": "G minor (Full barré). Fretboard: 3-5-5-3-3-3",

            # --- Dominant Seventh Chords ---
            "A7": "A dominant 7th. Fretboard: X-0-2-0-2-0",
            "B7": "B dominant 7th. Fretboard: X-2-1-2-0-2",
            "C7": "C dominant 7th. Fretboard: X-3-2-3-1-0",
            "D7": "D dominant 7th. Fretboard: X-X-0-2-1-2",
            "E7": "E dominant 7th. Fretboard: 0-2-0-1-0-0",
            "F7": "F dominant 7th (Barré). Fretboard: 1-3-1-2-1-1",
            "G7": "G dominant 7th. Fretboard: 3-2-0-0-0-1",

            # --- Minor Seventh Chords ---
            "Am7": "A minor 7th. Fretboard: X-0-2-0-1-0",
            "Bm7": "B minor 7th (Barré). Fretboard: X-2-4-2-3-2",
            "Cm7": "C minor 7th (Barré). Fretboard: X-3-5-3-4-3",
            "Dm7": "D minor 7th. Fretboard: X-X-0-2-1-1",
            "Em7": "E minor 7th. Fretboard: 0-2-0-0-0-0",
            "Fm7": "F minor 7th (Barré). Fretboard: 1-3-1-1-1-1",
            "Gm7": "G minor 7th (Barré). Fretboard: 3-5-3-3-3-3",

            # --- Major Seventh Chords ---
            "Amaj7": "A major 7th. Fretboard: X-0-2-1-2-0",
            "Bmaj7": "B major 7th. Fretboard: X-2-4-3-4-2",
            "Cmaj7": "C major 7th. Fretboard: X-3-2-0-0-0",
            "Dmaj7": "D major 7th. Fretboard: X-X-0-2-2-2",
            "Emaj7": "E major 7th. Fretboard: 0-2-1-1-0-0",
            "Fmaj7": "F major 7th. Fretboard: X-X-3-2-1-0",
            "Gmaj7": "G major 7th. Fretboard: 3-2-0-0-0-2",
            # --- A# / Bb Chords ---
            "A#": "A# major (Barré on 1st fret). Fretboard: X-1-3-3-3-1",
            "A#m": "A# minor (Barré on 1st fret). Fretboard: X-1-3-3-2-1",
            "A#7": "A# dominant 7th. Fretboard: X-1-3-1-3-1",
            "A#m7": "A# minor 7th. Fretboard: X-1-3-1-2-1",
            "A#maj7": "A# major 7th. Fretboard: X-1-3-2-3-1",
            # --- C# / Db Serie ---
            "C#": "C# major (Barré on 4th fret). Fretboard: X-4-6-6-6-4",
            "C#m": "C# minor. Fretboard: X-4-6-6-5-4",
            "C#7": "C# dominant 7th. Fretboard: X-4-6-4-6-4",

            # --- D# / Eb Serie ---
            "D#": "D# major. Fretboard: X-6-8-8-8-6",
            "Eb": "Eb major (Same as D#). Fretboard: X-6-8-8-8-6",
            "D#m": "D# minor. Fretboard: X-6-8-8-7-6",

            # --- F# / Gb Serie ---
            "F#": "F# major (Barré on 2nd fret). Fretboard: 2-4-4-3-2-2",
            "F#m": "F# minor. Fretboard: 2-4-4-2-2-2",
            "F#7": "F# dominant 7th. Fretboard: 2-4-2-3-2-2",

            # --- G# / Ab Serie ---
            "G#": "G# major (Barré on 4th fret). Fretboard: 4-6-6-5-4-4",
            "G#m": "G# minor. Fretboard: 4-6-6-4-4-4",
            "Ab": "Ab major (Same as G#). Fretboard: 4-6-6-5-4-4",
            # --- Slash Chords (Basnotes) ---
            "Em7/D": "Em7 with a D in the bass. Fretboard: X-5-5-4-5-X or open: 0-2-0-0-0-2",
            "C/G": "C major with a G in the bass. Fretboard: 3-3-2-0-1-0",
            "D/F#": "D major with an F# in the bass (often played with the thumb). Fretboard: 2-0-0-2-3-2",
            "G/B": "G major with a B in the bass. Fretboard: X-2-0-0-3-3",
            "Am/G": "A minor with a G in the bass. Fretboard: 3-0-2-2-1-0",

            # --- Suspended & Added Chords ---
            "Asus4": "A chord where the 3rd is replaced by the 4th (D). Fretboard: X-0-2-2-3-0",
            "Dsus4": "D chord where the 3rd is replaced by the 4th (G). Fretboard: X-X-0-2-3-3",
            "Asus2": "A chord where the 3rd is replaced by the 2nd (B). Fretboard: X-0-2-2-0-0",
            "Cadd9": "C major chord with an added 9th (D). Fretboard: X-3-2-0-3-3",
            "Gadd9": "G major chord with an added 9th (A). Fretboard: 3-2-0-2-0-3",

            # --- Diminished & Augmented ---
            "Adim": "A diminished chord (1-b3-b5). Fretboard: X-X-1-2-1-2",
            "Gdim": "G diminished chord. Fretboard: X-X-2-3-2-3",
            "Eaug": "E augmented chord (1-3-#5). Fretboard: 0-3-2-1-1-0",

            # --- Complex Extensions ---
            "A7sus4": "A dominant 7th with a suspended 4th. Fretboard: X-0-2-0-3-0",
            "E7#9": "The 'Hendrix Chord' (E7 with a sharp 9th). Fretboard: 0-7-6-7-8-X",
            "Fmaj7": "F major with a major 7th (E). Fretboard: 1-3-3-2-1-0 or X-X-3-2-1-0",
            "Gsus4": "G chord where the 3rd is replaced by the 4th (C). Fretboard: 3-2-0-0-1-3",
            "Fsus4": "F chord where the 3rd is replaced by the 4th (Bb). Fretboard: 1-3-3-3-1-1",
            "Cadd4": "C major chord with an added 4th (F). Common in 'Angie'. Fretboard: X-3-3-0-1-0",
            # --- Minor Major Seventh ---
            "EmM7": "E minor chord with a major 7th (D#). Often called the 'Spy chord'. Fretboard: 0-2-1-0-0-0",

            # --- Seventh Suspended ---
            "G7sus": "G dominant 7th with a suspended 4th (C) instead of a 3rd. Fretboard: 3-5-3-5-3-3 or 3-3-0-0-1-1",

            # --- Inversions & Slash Chords ---
            "F/A": "F major chord with an A in the bass (1st inversion). Fretboard: X-0-3-2-1-1",
            "G/B": "G major chord with a B in the bass (1st inversion). Fretboard: X-2-0-0-0-3",
            "G/A": "G major chord with an A in the bass. Creates a lush 9th sound. Fretboard: X-0-0-0-0-3",
            "D/E": "D major chord with an E in the bass. Often used as a dominant E9sus. Fretboard: 0-0-0-2-3-2"
        }


class ChordInfoManager:
    def __init__(self):
        # Dictionary containing chord names and their corresponding descriptions
        self.explanations = CHORD_EXPLANATIONS

        # Regex for chords: starts with A-G, optional # or b,
        # followed by alphanumeric characters, slashes, or sharps/flats
        self.chord_pattern = r'[A-G][#b]?[a-zA-Z0-9/#b]*'

    def get_chord_at_index(self, text_widget, event):
        """
        Locates which chord is under the mouse cursor.
        """
        # Convert pixel coordinates to text index
        idx = text_widget.index(f"@{event.x},{event.y}")

        # Get start and end of the specific line
        line_start = text_widget.index(f"{idx} linestart")
        line_end = text_widget.index(f"{idx} lineend")
        line_text = text_widget.get(line_start, line_end)

        # Calculate character offset within the line
        char_offset = int(idx.split('.')[1])

        # Find all chord matches in the line
        matches = re.finditer(self.chord_pattern, line_text)

        for match in matches:
            # Check if the cursor offset falls within the match boundaries
            if match.start() <= char_offset <= match.end():
                # Clean the chord string from trailing dots or slashes
                word = match.group().rstrip('./')
                return word
        return None

    def show_menu(self, app_root, text_widget, event):
        """
        Constructs and displays the context menu for chord info.
        """
        chord = self.get_chord_at_index(text_widget, event)
        if not chord:
            return

        explanation = self.explanations.get(chord)
        if explanation:
            # Initialize a popup menu
            menu = tk.Menu(app_root, tearoff=0)
            menu.add_command(label=f"CHORD: {chord}", state=tk.DISABLED)
            menu.add_separator()

            # Split data into description and fretboard pattern
            parts = explanation.split("Fretboard:")

            # Part 1: Textual explanation
            menu.add_command(label=parts[0].strip(), command=lambda: None)

            # Part 2: Fingering/Diagram (if present)
            if len(parts) > 1:
                fret_val = parts[1].strip()
                menu.add_command(
                    label=f"Fingering: {fret_val}",
                    command=lambda: self.draw_chord_diagram(app_root, chord, fret_val)
                )

            # Display the menu at the cursor position
            menu.post(event.x_root, event.y_root)

    def draw_chord_diagram(self, app_root, chord_name, fret_string):
        """
        Creates a popup window with a visual guitar chord diagram.
        Expects fret_string format: 'X-3-2-0-1-0'
        """
        # Extract the numeric/X part of the fret string
        clean_fret_string = fret_string.split(' ')[0].strip()

        # Clean the input (remove redundant prefix if still present)
        clean_frets = clean_fret_string.replace("Fretboard:", "").strip().split('-')

        # Setup the popup window
        top = tk.Toplevel(app_root)
        top.title(f"Diagram: {chord_name}")
        top.geometry("250x320")
        top.configure(bg="#2C2C2C")

        # Canvas for drawing the diagram
        c = tk.Canvas(top, width=200, height=250, bg="#2C2C2C", highlightthickness=0)
        c.pack(pady=20)

        # Grid constants for drawing
        margin_x, margin_y = 40, 40
        string_spacing = 25
        fret_spacing = 35

        # Draw Frets (Horizontal lines - 5 frets total)
        for i in range(6):
            y = margin_y + (i * fret_spacing)
            line_width = 4 if i == 0 else 1  # Thicker line for the nut (fret 0)
            c.create_line(margin_x, y, margin_x + 125, y, fill="white", width=line_width)

        # Draw Strings (Vertical lines - 6 strings)
        for i in range(6):
            x = margin_x + (i * string_spacing)
            c.create_line(x, margin_y, x, margin_y + 175, fill="#AAAAAA")

        # Draw Fingers / Markers based on the fret string
        for i, fret in enumerate(clean_frets):
            x = margin_x + (i * string_spacing)

            if fret.upper() == 'X':
                # Draw a red X for muted strings
                c.create_text(x, margin_y - 15, text="X", fill="#FF5555", font=("Arial", 10, "bold"))
            elif fret == '0':
                # Draw a green O for open strings
                c.create_oval(x - 5, margin_y - 20, x + 5, margin_y - 10, outline="#55FF55", width=2)
            else:
                # Draw a solid blue circle for pressed frets
                try:
                    f_num = int(fret)
                    # Calculate center position of the fret space
                    y = margin_y + (f_num * fret_spacing) - (fret_spacing / 2)
                    c.create_oval(x - 8, y - 8, x + 8, y + 8, fill="#2196F3", outline="white")
                except ValueError:
                    continue  # Skip if parsing fails

        # Display the chord name at the bottom
        tk.Label(top, text=chord_name, fg="white", bg="#2C2C2C", font=("Arial", 14, "bold")).pack()

class SongbookPDFGenerator:
    def __init__(self, songs_data):
        self.songs = songs_data

    def _generate_html(self, filename="Songbook.pdf"):
        # Initialize HTML structure with CSS for A4 page layout and styling
        html_content = f"""
        <html>
        <head>
            <style>
                @page {{
                    size: A4;
                    margin: 1.5cm;
                    @bottom-left {{
                        content: "{filename}";
                        font-size: 9pt;
                        color: #666;
                    }}
                    @bottom-right {{
                        content: "Page " counter(page);
                        font-size: 9pt;
                        color: #666;
                    }}
                }}
                body {{ font-family: 'DejaVu Sans', sans-serif; line-height: 1.05; }} /* Reduced line-height */

                .song-container {{
                    page-break-before: always;
                    page-break-inside: avoid; /* Stronger hint for WeasyPrint */
                    break-inside: avoid;
                    position: relative;
                }}

                .line {{ 
                    display: block; 
                    margin-bottom: 2px; /* Slightly less margin between lines */
                    white-space: pre; 
                    font-family: 'DejaVu Sans Mono', monospace; 
                    page-break-inside: avoid; /* Don't split a chord-lyric pair */
                    widows: 5; 
                    orphans: 5;
                }}
                /* Table of Contents Styling */
                .index-page {{ page-break-after: always; }}
                .index-entry {{ margin-bottom: 10px; font-family: sans-serif; }}
                .index-entry a {{ display: flex; text-decoration: none; color: black; align-items: baseline; }}
                .song-title {{ flex-shrink: 0; }}
                .index-entry a::after {{ content: target-counter(attr(href), page); margin-left: 5px; }}
                .dots {{ flex-grow: 1; border-bottom: 1px dotted #999; margin: 0 5px; }}
                /* Song Container Layouts */
                .song-container {{
                    page-break-before: always;
                    position: relative;
                }}

                /* Hard limit for Cases 1, 2, and 3 to ensure content fits on a single page */
                .single-page-limit {{
                    height: 24.5cm; /* Maximum height on A4 including margins */
                    overflow: hidden; /* Clips lines that exceed the page height */
                }}

                .song-header {{ border-bottom: 2px solid #2196F3; margin-bottom: 15px; column-span: all; }}
                .layout-columns {{ column-count: 2; column-gap: 1cm; column-rule: 1px solid #ccc; }}
                .layout-single {{ column-count: 1; }}

                /* Typography for Lyrics and Chords */
                /* Note: Using Monospace is critical for vertical alignment of chords */

                .chord-row {{ display: block; height: 1.1em; color: #d32f2f; font-weight: bold; font-family: inherit;}}
                .text-row {{ display: block; color: #000; font-family: inherit;}}


                /* Message displayed when content is clipped */
                .omitted-msg {{
                    position: absolute;
                    bottom: -1cm;
                    right: 0;
                    font-size: 8pt;
                    color: #f44336;
                    font-style: italic;
                    background: white;
                    padding-left: 10px;
                }}

                .comment {{ font-style: italic; color: #666; margin: 10px 0; font-family: sans-serif; font-size: 0.9em; }}
            </style>
        </head>
        <body>
            <div class="index-page">
                <h1 style="text-align: center; color: #2196F3;">Table of Contents</h1>
                <div style="margin-top: 30px;">
                {" ".join([f'<div class="index-entry"><a href="#song-{i-1}"><span class="song-title">{i}. {s["artist"]} - {s["title"]}</span><span class="dots"></span></a></div>' for i, s in enumerate(self.songs, 1)])}
                </div>
            </div>
        """

        for i, song in enumerate(self.songs):
            # Determine the best layout and font size based on song length/width
            layout_style, font_size = self._analyze_song_layout(song['content'])

            # Apply single-page limit class except for multi-page songs (Case 4)
            limit_class = "single-page-limit" if font_size < 11 and "columns" in layout_style or font_size == 8.5 else ""

            # Show warning message only when clipping is active
            omitted_warning = '<div class="omitted-msg">... lines omitted (fixed to 1 page)</div>' if limit_class else ""

            # Process the ChordPro text into HTML layers
            formatted_content = self._format_chordpro_to_layers(song['content'])

            html_content += f"""
            <div class="song-container {layout_style} {limit_class}" id="song-{i}" style="font-size: {font_size}pt;">
                <div class="song-header">
                    <h2 style="margin:0;">{song['title']}</h2>
                    <p style="margin:0; color:#555;">{song['artist']}</p>
                </div>
                {formatted_content}
                {omitted_warning}
            </div>
            """

        html_content += "</body></html>"
        return html_content

    def _analyze_song_layout(self, text):
        """Analyzes song text with stricter limits to prevent single-line overflows."""
        lines = [l for l in text.split('\n') if l.strip()]
        total_lines = len(lines)
        max_char_width = max([len(re.sub(r'\[.*?\]', '', l)) for l in lines]) if lines else 0

        # Case 2: Two Columns
        if max_char_width <= 42:
            if 35 <= total_lines < 70: # Lowered from 75 to 70
                return "layout-columns", (8.5 if max_char_width > 35 else 10)
            elif total_lines < 35:
                return "layout-single", 10

        # Case 3: Rescue Single Page
        # If the song has more than 38 lines, we now drop to 8.5pt sooner
        if 36 <= total_lines <= 55: # Changed 38 to 36
            return "layout-single", 8.5

        return "layout-single", 10

    def _format_chordpro_to_layers(self, text):
        """Translates ChordPro format into two HTML layers: chords (top) and lyrics (bottom)."""
        html_lines = []
        for line in text.split('\n'):
            line = line.strip('\r')
            # Skip empty lines or metadata tags (excluding comments)
            if not line or (line.startswith('{') and not (
                    line.lower().startswith('{c:') or line.lower().startswith('{comment:'))):
                continue

            # Handle ChordPro comments/directives
            if line.lower().startswith('{c:') or line.lower().startswith('{comment:'):
                comment_text = re.sub(r'\{(?:c|comment):\s*(.*)\}', r'\1', line, flags=re.IGNORECASE).strip('}')
                html_lines.append(f'<div class="comment">({comment_text})</div>')
                continue

            # Process chord positioning
            # Note: current_text_pos tracks indices without ChordPro brackets
            chords = ""
            current_text_pos = 0

            # Split line into segments of text and [Chord] tags
            parts = re.split(r'(\[.*?\])', line)
            for part in parts:
                if part.startswith('[') and part.endswith(']'):
                    chord_name = part[1:-1]
                    # Add non-breaking spaces to match the character count of lyrics
                    chords += "&nbsp;" * (
                            current_text_pos - len(re.sub(r'&nbsp;', ' ', chords.replace(chord_name, ''))))
                    pass

            # Calculate precise placement using a character array to handle overlaps
            chord_row = [" "] * 150
            clean_text = ""
            pos_in_text = 0

            parts = re.split(r'(\[.*?\])', line)
            for part in parts:
                if part.startswith('[') and part.endswith(']'):
                    chord_text = part[1:-1]
                    for i, char in enumerate(chord_text):
                        if pos_in_text + i < len(chord_row):
                            chord_row[pos_in_text + i] = char
                else:
                    clean_text += part
                    pos_in_text += len(part)

            # Convert to HTML entities for proper rendering in browser/PDF
            final_chords = "".join(chord_row).rstrip().replace(" ", "&nbsp;")
            final_lyrics = clean_text.replace(" ", "&nbsp;")

            html_lines.append(
                f'<div class="line"><span class="chord-row">{final_chords if final_chords else "&nbsp;"}</span><span class="text-row">{final_lyrics if final_lyrics else "&nbsp;"}</span></div>')
        return "".join(html_lines)

    def generate(self, output_path):
        """Generates the final PDF using the WeasyPrint library."""
        import os
        filename = os.path.basename(output_path)
        # Pass the filename to the HTML template for the footer
        html_string = self._generate_html(filename=filename)
        HTML(string=html_string).write_pdf(output_path)

class TouchFileList(tk.Toplevel):
    def __init__(self, parent, callback, parent_object):
        super().__init__(parent)
        self.parent = parent_object
        self.title("Song Library Pro")
        # Ensure the window takes up the full screen for a touch-friendly interface
        self.attributes("-fullscreen", True)
        self.callback = callback
        self.tags_file = "tags.json"

        # 1. Variables & State
        self.active_tag = "All"
        self.sort_song_by = "none"
        self.metadata_cache = {}
        self.all_files_cached = []
        self.tags = {}
        self.current_song_data = []

        # 2. Colors & Fonts
        self.colors = {
            "bg": "#f5f5f5",
            "sidebar": "#eceff1",
            "accent": "#2196F3",
            "toolbar": "#cfd8dc",
            "danger": "#f44336",
            "success": "#4CAF50",
            "text": "#263238"
        }
        self.font_main = ("Arial", 16)
        self.font_ui = ("Arial", 12, "bold")

        # 3. Data Loading
        self.load_tags()
        self.update_file_cache()

        # 4. UI Initialization
        self.setup_ui()
        self.apply_settings()
        self.refresh_ui()

    # --- Data Management ---

    def load_tags(self):
        """Loads tag/category associations from a JSON file."""
        if os.path.exists(self.tags_file):
            try:
                with open(self.tags_file, 'r', encoding='utf-8') as f:
                    self.tags = json.load(f)
            except: self.tags = {}
        else: self.tags = {}

    def apply_settings(self):
        self.active_tag = self.parent.active_tag
        self.sort_song_by = self.parent.sort_song_by

    def save_tags(self):
        """Saves current tags and song associations to a JSON file."""
        with open(self.tags_file, 'w', encoding='utf-8') as f:
            json.dump(self.tags, f, indent=4)

    def update_file_cache(self):
        """Scans the directory for .cho files and updates the internal cache."""
        all_files = []
        for root, _, files in os.walk('.'):
            for file in files:
                if file.endswith('.cho'):
                    all_files.append(os.path.relpath(os.path.join(root, file), '.'))
        self.all_files_cached = sorted(all_files)

    def get_song_metadata(self, path):
        """Extracts Title and Artist from ChordPro tags, with caching."""
        if path in self.metadata_cache: return self.metadata_cache[path]
        meta = {"title": os.path.basename(path), "artist": "Unknown", "path": path}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for _ in range(15):
                    line = f.readline()
                    if not line: break
                    low_line = line.lower()
                    if "{t:" in low_line or "{title:" in low_line:
                        meta["title"] = line.split(":", 1)[1].strip("} \n")
                    elif "{a:" in low_line or "{artist:" in low_line:
                        meta["artist"] = line.split(":", 1)[1].strip("} \n")
        except: pass
        self.metadata_cache[path] = meta
        return meta

    # --- Selection Helpers ---

    def select_all_songs(self):
        """Selects every item currently visible in the song listbox."""
        self.song_listbox.select_set(0, tk.END)

    def select_none_songs(self):
        """Clears all selections in the song listbox."""
        self.song_listbox.selection_clear(0, tk.END)

    # --- OSSB Export Logic (Threaded) ---

    def generate_ossb_from_selection(self):
        """Initiates the OSSB archive creation in a background thread."""
        selection = self.song_listbox.curselection()

        if not selection:
            if messagebox.askyesno("OSSB Export", "No songs selected. Export all songs in this list?", parent=self):
                selected_paths = [item["path"] for item in self.current_song_data]
            else: return
        else:
            selected_paths = [self.current_song_data[i]["path"] for i in selection]

        default_name = f"Set_{self.active_tag}.ossb"
        output_file = simpledialog.askstring("Save OSSB", "Filename:", initialvalue=default_name, parent=self)
        if not output_file: return

        base_name = os.path.splitext(os.path.basename(output_file))[0]
        if not output_file.endswith('.ossb'): output_file += '.ossb'

        self.btn_ossb.config(state=tk.DISABLED, text="⌛ BUSY...")

        thread = threading.Thread(
            target=self._ossb_worker,
            args=(selected_paths, output_file, base_name),
            daemon=True
        )
        thread.start()

    def _ossb_worker(self, selected_paths, output_file, base_name):
        """Background worker with safety checks for closed windows."""
        files_written = 0
        index_entries = []

        try:
            with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as ossb_zip:
                for path in selected_paths:
                    meta = self.get_song_metadata(path)
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                        ost_xml = self._create_ost_xml(meta, content)
                        safe_name = "".join(x for x in meta['title'] if x.isalnum() or x in " -_").strip()
                        if not safe_name: safe_name = "Untitled_Song"
                        ost_filename = f"{safe_name}.ost"
                        ossb_zip.writestr(ost_filename, ost_xml)
                        index_entries.append({'name': meta['title'], 'filename': ost_filename})
                        files_written += 1
                    except Exception as e:
                        print(f"Error processing {path}: {e}")

                if files_written > 0:
                    index_xml = self._create_osts_index(base_name, index_entries)
                    ossb_zip.writestr(f"{base_name}.osts", index_xml)

            # Safety check before showing popups
            if not self.winfo_exists(): return

            if files_written > 0:
                self.after(0, lambda: messagebox.showinfo("Success", f"OSSB created.", parent=self) if self.winfo_exists() else None)
            else:
                self.after(0, lambda: messagebox.showwarning("Warning", "No songs added.", parent=self) if self.winfo_exists() else None)

        except Exception as e:
            if self.winfo_exists():
                self.after(0, lambda: messagebox.showerror("Error", f"OSSB failed: {e}", parent=self) if self.winfo_exists() else None)
        finally:
            if self.winfo_exists():
                self.after(0, lambda: self.btn_ossb.config(state=tk.NORMAL, text="OSSB 📦"))

    def _create_osts_index(self, set_name, entries):
        """Helper to create the XML for the .osts index file."""
        set_uuid = str(uuid.uuid4())
        timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')[:-3] + 'Z'
        groups_xml = ""
        for entry in entries:
            groups_xml += f'  <slide_group name="{entry["name"]}" type="song" path="/" prefKey=""/>\n'

        index_template = f"""<?xml version="1.0" encoding="utf-8"?>
<set name="{set_name}">
<slide_groups>
{groups_xml}</slide_groups>
<uuid>{set_uuid}</uuid>
<lastModified>{timestamp}</lastModified>
<notes></notes>
</set>"""
        return index_template.encode('utf-8')

    def _create_ost_xml(self, meta, content):
        """Creates an .ost XML string using a strictly validated template."""
        song_uuid = str(uuid.uuid4())
        timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        template = f"""<?xml version="1.0" encoding="UTF-8"?>
<song>
  <uuid>{song_uuid}</uuid>
  <last_modified>{timestamp}</last_modified>
  <title>{meta['title']}</title>
  <author>{meta['artist']}</author>
  <copyright>{meta['artist']}</copyright>
  <presentation></presentation>
  <hymn_number></hymn_number>
  <capo print="false"></capo>
  <tempo>0</tempo>
  <time_sig>4/4</time_sig>
  <duration></duration>
  <predelay>2</predelay>
  <ccli></ccli>
  <theme></theme>
  <alttheme></alttheme>
  <user1></user1>
  <user2></user2>
  <user3></user3>
  <beatbuddysong></beatbuddysong>
  <beatbuddykit></beatbuddykit>
  <key></key>
  <keyoriginal></keyoriginal>
  <aka></aka>
  <midi></midi>
  <midi_index></midi_index>
  <notes></notes>
  <lyrics>{content}</lyrics>
  <pad_file>Auto</pad_file>
  <custom_chords></custom_chords>
  <link_youtube></link_youtube>
  <link_web></link_web>
  <link_audio></link_audio>
  <loop_audio>false</loop_audio>
  <link_other></link_other>
  <abcnotation></abcnotation>
  <abctranspose>0</abctranspose>
  <backgrounds resize="screen" keep_aspect="false" link="false" background_as_text="false"/>
</song>"""
        return template.encode('utf-8')

    # --- PDF Export Logic (Threaded) ---

    def generate_pdf_from_selection(self):
        """Initiates the PDF generation process using a background thread."""
        selection = self.song_listbox.curselection()

        if not selection:
            if messagebox.askyesno("PDF Export", "No songs selected. Export the entire current list?", parent=self):
                selected_paths = [item["path"] for item in self.current_song_data]
            else: return
        else:
            selected_paths = [self.current_song_data[i]["path"] for i in selection]

        default_name = f"Songbook_{self.active_tag}.pdf"
        output_file = simpledialog.askstring("Save PDF", "Filename:", initialvalue=default_name, parent=self)

        if not output_file: return
        if not output_file.endswith('.pdf'): output_file += '.pdf'

        self.btn_pdf.config(state=tk.DISABLED, text="⌛ BUSY...")

        thread = threading.Thread(
            target=self._pdf_worker,
            args=(selected_paths, output_file),
            daemon=True
        )
        thread.start()

    def _pdf_worker(self, selected_paths, output_file):
        """Background worker with visual progress updates."""
        # 1. Show the progress bar
        self.after(0, lambda: self.progress_frame.pack(side=tk.BOTTOM, fill=tk.X))

        full_song_data = []
        total = len(selected_paths)

        for i, path in enumerate(selected_paths):
            # Check if window still exists
            if not self.winfo_exists(): return

            meta = self.get_song_metadata(path)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                full_song_data.append({'title': meta['title'], 'artist': meta['artist'], 'content': content})
            except Exception as e:
                print(f"Error reading {path}: {e}")

            # Update progress bar: (current / total) * 100
            progress = ((i + 1) / total) * 100
            self.after(0, lambda p=progress, t=meta['title']: self._update_progress(p, f"Reading: {t}"))

        if not full_song_data or not self.winfo_exists():
            self._cleanup_pdf_task()
            return

        try:
            # Update label to show rendering status
            self.after(0, lambda: self.progress_label.config(text="Generating PDF layout (please wait)..."))

            gen = SongbookPDFGenerator(full_song_data)
            gen.generate(output_file)

            self.after(0, lambda: messagebox.showinfo("Success", f"PDF created: {output_file}",
                                                      parent=self) if self.winfo_exists() else None)
        except Exception as e:
            err_msg = str(e)
            self.after(0, lambda: messagebox.showerror("Error", f"Failed: {err_msg}",
                                                       parent=self) if self.winfo_exists() else None)
        finally:
            self._cleanup_pdf_task()

    def _update_progress(self, value, text):
        """Helper to safely update progress UI."""
        if self.winfo_exists():
            self.progress_var.set(value)
            self.progress_label.config(text=text)

    def _cleanup_pdf_task(self):
        """Hides progress bar and resets UI buttons."""
        if self.winfo_exists():
            self.progress_frame.pack_forget()
            self.btn_pdf.config(state=tk.NORMAL, text="PDF 📄")

    # --- UI Setup & Refresh ---

    def setup_ui(self):
        """Builds the main graphical interface with touch-optimized components."""
        header = tk.Frame(self, bg=self.colors["accent"], height=80)
        header.pack(fill=tk.X)
        # Store as self.header_label to update it during tag selection
        self.header_label = tk.Label(header, text="🎵 LIBRARY", fg="white",
                                     bg=self.colors["accent"], font=("Arial", 22, "bold"))
        self.header_label.pack(pady=20)

        main_container = tk.Frame(self, bg=self.colors["bg"])
        main_container.pack(fill=tk.BOTH, expand=True)

        # LEFT COLUMN: CATEGORIES
        left_col = tk.Frame(main_container, bg=self.colors["sidebar"], width=300)
        left_col.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)

        tk.Label(left_col, text="TAGS", bg=self.colors["toolbar"], font=self.font_ui).pack(fill=tk.X, ipady=10)
        self.tag_listbox = tk.Listbox(left_col, font=self.font_main, bg="white",
                                      selectbackground=self.colors["accent"], activestyle='none')
        self.tag_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.tag_listbox.bind('<<ListboxSelect>>', self._on_tag_select)

        self.btn_tag_edit_frame = tk.Frame(left_col, bg=self.colors["sidebar"])
        tk.Button(self.btn_tag_edit_frame, text="RENAME", font=self.font_ui, height=2,
                  command=self.rename_tag).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        tk.Button(self.btn_tag_edit_frame, text="DELETE", font=self.font_ui, height=2, bg=self.colors["danger"],
                  fg="white", command=self.delete_tag).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        # RIGHT COLUMN: SONGS
        right_col = tk.Frame(main_container, bg=self.colors["bg"])
        right_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        search_frame = tk.Frame(right_col, bg=self.colors["toolbar"], pady=10)
        search_frame.pack(fill=tk.X)
        tk.Label(search_frame, text="  🔍  ", bg=self.colors["toolbar"], font=("Arial", 18)).pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.refresh_ui())
        self.search_entry = tk.Entry(search_frame, textvariable=self.search_var, font=("Arial", 20))
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        tool_bar = tk.Frame(right_col, bg=self.colors["bg"], pady=10)
        tool_bar.pack(fill=tk.X)

        tk.Label(tool_bar, text="Sort:", bg=self.colors["bg"], font=self.font_ui).pack(side=tk.LEFT, padx=5)
        for lbl, m in [("Name", "name"), ("Artist", "artist"), ("None", "none")]:
            tk.Button(tool_bar, text=lbl, command=lambda mode=m: self.set_song_sort(mode),
                      width=7, height=2, font=self.font_ui).pack(side=tk.LEFT, padx=5)

        tk.Button(tool_bar, text="☑ ALL", bg="#78909C", fg="white", font=self.font_ui,
                  height=2, command=self.select_all_songs).pack(side=tk.LEFT, padx=5)
        tk.Button(tool_bar, text="☐ NONE", bg="#78909C", fg="white", font=self.font_ui,
                  height=2, command=self.select_none_songs).pack(side=tk.LEFT, padx=5)

        self.btn_reorder = tk.Button(tool_bar, text="✍️ ORDER", bg="#FF9800", fg="white",
                                     font=self.font_ui, height=2, command=self.open_reorder_window)
        self.btn_reorder.pack(side=tk.RIGHT, padx=5)

        tk.Button(tool_bar, text="➕ TAG", bg=self.colors["success"], fg="white",
                  font=self.font_ui, height=2, command=self.create_tag_from_selection).pack(side=tk.RIGHT, padx=5)
        self.btn_pdf = tk.Button(tool_bar, text="PDF 📄", bg="#607D8B", fg="white",
                                 font=self.font_ui, height=2, command=self.generate_pdf_from_selection)
        self.btn_pdf.pack(side=tk.RIGHT, padx=5)
        self.btn_ossb = tk.Button(tool_bar, text="OSSB 📦", bg="#9C27B0", fg="white",
                                  font=self.font_ui, height=2, command=self.generate_ossb_from_selection)
        self.btn_ossb.pack(side=tk.RIGHT, padx=5)

        list_frame = tk.Frame(right_col)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.song_listbox = tk.Listbox(list_frame, font=self.font_main, bg="white",
                                       selectmode=tk.MULTIPLE, activestyle='none')
        self.song_scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self.song_listbox.yview, width=60)
        self.song_listbox.configure(yscrollcommand=self.song_scrollbar.set)
        self.song_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.song_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.song_listbox.bind('<Double-1>', lambda e: self.confirm_selection())

        # --- Progress Bar for long tasks ---
        from tkinter import ttk
        self.progress_frame = tk.Frame(right_col, bg=self.colors["bg"])
        # Initially hidden until needed
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(self.progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, padx=10, pady=5)
        self.progress_label = tk.Label(self.progress_frame, text="Processing...", bg=self.colors["bg"],
                                       font=("Arial", 10))
        self.progress_label.pack()

        footer = tk.Frame(self, bg=self.colors["toolbar"])
        footer.pack(fill=tk.X)
        tk.Button(footer, text="OPEN SELECTED SONG", font=("Arial", 16, "bold"),
                  bg=self.colors["accent"], fg="white", height=3, command=self.confirm_selection).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(footer, text="CLOSE", font=("Arial", 14), bg="#607D8B",
                  fg="white", height=3, width=20, command=self.destroy).pack(side=tk.RIGHT)

    def refresh_ui(self):
        """Updates the listboxes and provides visual feedback for the active category."""
        # 1. Update Header Text
        # Update the top banner to show exactly which category is currently active
        display_tag = self.active_tag.upper()
        self.header_label.config(text=f"🎵 LIBRARY: {display_tag}")

        # 2. Update Tags List
        self.tag_listbox.delete(0, tk.END)
        tags_to_show = ["All"] + sorted(self.tags.keys())

        for i, t in enumerate(tags_to_show):
            count = len(self.all_files_cached) if t == "All" else len(self.tags.get(t, []))
            self.tag_listbox.insert(tk.END, f"\n {t.upper()} ({count}) \n")

            # Force the selection highlight to stay visible
            if t == self.active_tag:
                self.tag_listbox.selection_set(i)
                self.tag_listbox.activate(i)
                # Optional - change background of the active item for extra contrast
                self.tag_listbox.itemconfig(i, bg="#e3f2fd", fg=self.colors["accent"])

        if self.active_tag == "All":
            self.btn_reorder.pack_forget()
            self.btn_tag_edit_frame.pack_forget()
        else:
            self.btn_reorder.pack(side=tk.RIGHT, padx=5)
            self.btn_tag_edit_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=5)

        self.song_listbox.delete(0, tk.END)
        raw_paths = self.all_files_cached if self.active_tag == "All" else self.tags.get(self.active_tag, [])
        search_term = self.search_var.get().lower()

        self.current_song_data = []
        for p in raw_paths:
            if p not in self.all_files_cached: continue
            meta = self.get_song_metadata(p)
            match = search_term in meta["title"].lower() or search_term in meta["artist"].lower()
            if not match and len(search_term) > 2:
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        if search_term in f.read().lower(): match = True
                except: pass
            if match: self.current_song_data.append(meta)

        if self.sort_song_by == "artist": self.current_song_data.sort(key=lambda x: x["artist"].lower())
        elif self.sort_song_by == "title": self.current_song_data.sort(key=lambda x: x["title"].lower())
        elif self.sort_song_by == "name": self.current_song_data.sort(key=lambda x: x["path"].lower())

        for item in self.current_song_data:
            display = f"{item['artist']} - {item['title']}" if item['artist'] != "Unknown" else item['title']
            self.song_listbox.insert(tk.END, f"  {display}  ")

    # --- Interaction Handlers ---
    def save_settings(self):
        self.parent.save_settings()

    def _on_tag_select(self, event):
        selection = self.tag_listbox.curselection()
        if selection:
            tags_to_show = ["All"] + sorted(self.tags.keys())
            self.active_tag = tags_to_show[selection[0]]
            self.parent.active_tag = self.active_tag
            self.save_settings()
            self.refresh_ui()

    def set_song_sort(self, mode):
        self.sort_song_by = mode
        self.parent.sort_song_by = self.sort_song_by
        self.save_settings()
        self.refresh_ui()

    def rename_tag(self):
        if self.active_tag == "All": return
        new_name = simpledialog.askstring("Rename", f"New name for '{self.active_tag}':", parent=self)
        if new_name and new_name not in self.tags:
            self.tags[new_name] = self.tags.pop(self.active_tag)
            self.save_tags()
            self.active_tag = new_name
            self.refresh_ui()

    def delete_tag(self):
        if self.active_tag == "All": return
        if messagebox.askyesno("Delete", f"Delete category '{self.active_tag}'?", parent=self):
            del self.tags[self.active_tag]
            self.save_tags()
            self.active_tag = "All"
            self.refresh_ui()

    def confirm_selection(self):
        selection = self.song_listbox.curselection()
        if not selection: return
        chosen_path = self.current_song_data[selection[0]]["path"]
        playlist = [item["path"] for item in self.current_song_data]
        self.callback(chosen_path, playlist=playlist)
        self.destroy()

    def create_tag_from_selection(self):
        selection = self.song_listbox.curselection()
        if not selection:
            messagebox.showwarning("Selection", "Please select songs first.", parent=self)
            return
        new_tag = simpledialog.askstring("New Tag", "Name for this category:", parent=self)
        if new_tag:
            if new_tag not in self.tags: self.tags[new_tag] = []
            for i in selection:
                p = self.current_song_data[i]["path"]
                if p not in self.tags[new_tag]: self.tags[new_tag].append(p)
            self.save_tags()
            self.active_tag = new_tag
            self.refresh_ui()

    def open_reorder_window(self):
        """Opens a dedicated fullscreen window to manually reorder songs."""
        if self.active_tag == "All": return

        reorder_win = tk.Toplevel(self)
        reorder_win.attributes("-fullscreen", True)
        reorder_win.configure(bg=self.colors["bg"])
        reorder_win.transient(self) # Keep on top of library
        reorder_win.grab_set()      # Block interaction with library

        tk.Label(reorder_win, text=f"ORDERING: {self.active_tag.upper()}", bg="#FF9800",
                 fg="white", font=("Arial", 20, "bold"), pady=20).pack(fill=tk.X)

        list_frame = tk.Frame(reorder_win, bg="white")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        lb = tk.Listbox(list_frame, font=self.font_main, activestyle='none')
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = tk.Scrollbar(list_frame, width=60, command=lb.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        lb.config(yscrollcommand=sb.set)

        def fill_lb():
            lb.delete(0, tk.END)
            for p in self.tags[self.active_tag]:
                m = self.get_song_metadata(p)
                lb.insert(tk.END, f"  {m['artist']} - {m['title']}  ")

        fill_lb()

        btn_bar = tk.Frame(reorder_win, pady=20, bg=self.colors["toolbar"])
        btn_bar.pack(fill=tk.X)

        def move(dir):
            sel = lb.curselection()
            if not sel: return
            idx = sel[0]
            new_idx = idx + dir
            lst = self.tags[self.active_tag]
            if 0 <= new_idx < len(lst):
                lst[idx], lst[new_idx] = lst[new_idx], lst[idx]
                self.save_tags()
                fill_lb()
                lb.selection_set(new_idx)

        def delete_item():
            sel = lb.curselection()
            if not sel: return
            if messagebox.askyesno("Remove", "Remove from this list?", parent=reorder_win):
                self.tags[self.active_tag].pop(sel[0])
                self.save_tags()
                fill_lb()

        tk.Button(btn_bar, text="▲ UP", width=12, height=3, font=self.font_ui, command=lambda: move(-1)).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_bar, text="▼ DOWN", width=12, height=3, font=self.font_ui, command=lambda: move(1)).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_bar, text="🗑 REMOVE", bg=self.colors["danger"], fg="white", width=12, height=3, font=self.font_ui, command=delete_item).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_bar, text="DONE", bg=self.colors["success"], fg="white", width=12, height=3, font=self.font_ui, command=lambda: [self.refresh_ui(), reorder_win.destroy()]).pack(side=tk.RIGHT, padx=10)


class PerformanceManager:
    """
    Handles live performance features including fullscreen mode,
    autoscrolling with countdown, and floating UI menus.
    """

    def __init__(self, app):
        self.app = app  # Reference to the main ChoConverterApp
        self.root = app.root
        self.is_scrolling = False
        self._scroll_job = None
        self._menu_timer_id = None

        # Floating widgets
        self.exit_perf_btn = None
        self.perf_menu_btn = None
        self.perf_menu_frame = None

    def enter_performance_mode(self):
        """Optimizes the screen for live performance by removing distractions."""
        self.app.is_performance_mode = True

        # 1. Hide Editor and Top navigation bars via the main app reference
        self.app.ui_manager.top_frame.pack_forget()
        self.app.ui_manager.editor_frame.pack_forget()
        self.app.ui_manager.view_frame.pack_forget()

        # 2. Activate Fullscreen mode
        self.root.attributes("-fullscreen", True)

        # 3. Scale the viewer to fill the entire screen
        self.app.viewer_main_frame.pack_configure(padx=0, pady=0)

        # 4. Create floating overlay buttons
        self.exit_perf_btn = tk.Button(self.root, text="✕ EXIT", command=self.exit_performance_mode,
                                       bg="#333333", fg="#888888", font=("Arial", 9),
                                       relief=tk.FLAT, padx=15, pady=10)
        self.exit_perf_btn.place(relx=1.0, rely=0.0, anchor="ne")

        self.perf_menu_btn = tk.Button(self.root, text="MENU ☰", command=self.toggle_perf_menu,
                                       bg="#2196F3", fg="white", font=("Arial", 12, "bold"),
                                       relief=tk.RAISED, padx=20, pady=15)
        self.perf_menu_btn.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)

        # Bind hardware keys
        self.root.bind("<Escape>", lambda e: self.exit_performance_mode())
        self.root.bind("<Right>", lambda e: self.app.next_song())

    def exit_performance_mode(self):
        """Restores the UI to standard View/Edit mode."""
        self.app.is_performance_mode = False
        self.root.attributes("-fullscreen", False)

        # Stop scrolling if active
        if self.is_scrolling:
            self.stop_scroll()

        # 1. Clean up floating elements
        if self.exit_perf_btn: self.exit_perf_btn.destroy()
        if self.perf_menu_btn: self.perf_menu_btn.destroy()
        if self.perf_menu_frame: self.perf_menu_frame.destroy()

        # 2. Restore standard layout via the main app
        #self.app.output_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.app.viewer_main_frame.pack_configure(padx=20, pady=(0, 10))

        # 3. Trigger normal UI restoration
        self.app.is_view_mode = True
        self.app.toggle_view_mode()

        # Update Fullscreen button state in main UI if it exists
        if hasattr(self.app, 'fs_btn'):
            self.app.fs_btn.config(text="📺 FULL SCREEN", bg="#2196F3")
            self.app.is_fullscreen = False

    def toggle_perf_menu(self):
        """Safely shows or hides the floating performance menu."""
        # Cancel any pending auto-hide timer when manually toggling
        if self._menu_timer_id:
            self.root.after_cancel(self._menu_timer_id)
            self._menu_timer_id = None

        if self.perf_menu_frame and self.perf_menu_frame.winfo_exists():
            if self.perf_menu_frame.winfo_viewable():
                self.hide_perf_menu()
                return
        else:
            # Parent should be self.app.root (consistency check)
            self.perf_menu_frame = tk.Frame(self.app.root, bg="#424242", padx=10, pady=10,
                                            highlightbackground="white", highlightthickness=1)

        # Clear and rebuild menu items
        for widget in self.perf_menu_frame.winfo_children():
            widget.destroy()

        options = [
            ("⏩ NEXT", self.perf_action_next, "#4CAF50"),
            ("🛑 STOP", self.perf_action_stop_scroll, "#f44336"),  # Rood voor Stop
            ("🔄 RESET", self.perf_action_reset_scroll, "#2196F3"),  # Blauw voor Reset
            ("▶ SCROLL", self.perf_action_scroll, "#FF9800"),
            ("🔍 A+", lambda: self.perf_action_font(2), "#607D8B"),
            ("🔅 A-", lambda: self.perf_action_font(-2), "#607D8B"),
            ("📑 COLS +", lambda: self.perf_action_columns(1), "#9C27B0"),
            ("📄 COLS -", lambda: self.perf_action_columns(-1), "#9C27B0")
        ]

        for text, cmd, color in options:
            tk.Button(self.perf_menu_frame, text=text, command=cmd,
                      bg=color, fg="white", font=("Arial", 11, "bold"),
                      width=15, height=2, pady=5).pack(pady=2)

        self.perf_menu_frame.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-85)

    def hide_perf_menu(self):
        """
        Hides the performance menu from view.
        Added safety check for winfo_exists to prevent TclErrors.
        """
        if self._menu_timer_id:
            self.root.after_cancel(self._menu_timer_id)
            self._menu_timer_id = None

        # Only attempt to hide if the widget actually exists
        if self.perf_menu_frame and self.perf_menu_frame.winfo_exists():
            self.perf_menu_frame.place_forget()

    def perf_action_next(self):
        """Closes menu and loads next song."""
        self.hide_perf_menu()
        self.app.next_song()

    def perf_action_scroll(self):
        """Closes menu and toggles autoscroll."""
        self.hide_perf_menu()
        self.toggle_scroll()

    def perf_action_stop_scroll(self):
        """
        Immediately stops the scrolling and hides the menu.
        """
        self.stop_scroll()
        self.hide_perf_menu()

    def perf_action_reset_scroll(self):
        """
        Resets the scroll position to the top without stopping.
        The menu stays open for further adjustments.
        """
        self.app.view_renderer.scroll_offset = 0.0
        self.app.view_renderer.render_scrolled_content()
        # Optional: restart the timer so the menu stays visible
        if self._menu_timer_id:
            self.root.after_cancel(self._menu_timer_id)
        self._menu_timer_id = self.root.after(3000, self.hide_perf_menu)

    def perf_action_columns(self, delta):
        """
        Forces the mode to 'Multi' and increments/decrements
         the number of potential columns to display.
        """

        # Access the wrapper
        wrapper = self.app.output_text
        # Adjust the desired number of columns
        new_count = max(1, min(wrapper.MAX_COLUMNS, wrapper.forced_multi_count + delta))

        # Force the mode to multi ("two") if it wasn't already
        wrapper.column_mode = "two"
        self.app.column_mode.set("two") # Sync UI radiobuttons
        if new_count < 1:
            # Switching back to auto mode if user tries to go below 1
            wrapper.column_mode = "auto"
            self.app.column_mode.set("auto")  # Sync UI radiobuttons
            print("Layout set to: AUTO")
        else:
            # Clamp and set fixed column count
            new_count = min(wrapper.MAX_COLUMNS, new_count)
            wrapper.forced_multi_count = new_count
            wrapper.column_mode = "two" if new_count > 1 else "one"
            self.app.column_mode.set(wrapper.column_mode)

        # 3. Re-render without hiding the menu
        self.app.render_view()
        if self._menu_timer_id:
            self.root.after_cancel(self._menu_timer_id)
        self._menu_timer_id = self.root.after(3000, self.hide_perf_menu)

    def perf_action_font(self, delta):
        """Adjusts font size and manages auto-hide timer."""
        self.app.change_font(delta)
        if self._menu_timer_id:
            self.root.after_cancel(self._menu_timer_id)
        self._menu_timer_id = self.root.after(3000, self.hide_perf_menu)

    def perf_action_layout(self):
        """
        Intelligently toggles between single and multi-column layouts
        based on the current visual state, even when in 'auto' mode.
        """
        self.hide_perf_menu()

        # Logic: If we see 1 column, switch to multi (two).
        # Otherwise (if we see 2, 3, or 4), switch to 1.
        if not self.app.view_renderer.multi:
            new_mode = "two"
        else:
            new_mode = "one"

        # Update the UI radiobuttons to match the new state
        self.app.column_mode.set(new_mode)

        # Apply the mode and trigger the re-render
        self.app.output_text.set_column_mode(new_mode)

    # --- Autoscroll Logic ---

    def toggle_scroll(self):
        """Toggles the autoscroll feature with lead-in countdown."""
        if self.is_scrolling:
            self.stop_scroll()
        else:
            self.is_scrolling = True
            self.app.scroll_btn.config(text="■ STOP", bg="#f44336")  # Sync main UI button
            self.start_countdown(10)

    def stop_scroll(self):
        """Immediately stops all scrolling activities."""
        self.is_scrolling = False
        self.app.scroll_btn.config(text="▶ START", bg="#FF9800")
        if self._scroll_job:
            self.root.after_cancel(self._scroll_job)

    def start_countdown(self, seconds):
        """Lead-in timer before actual scrolling starts."""
        if not self.is_scrolling: return

        if seconds > 0:
            self.app.scroll_btn.config(text=f"⏳ WAIT {seconds}", bg="#5bc0de")
            self.root.after(1000, lambda: self.start_countdown(seconds - 1))
        else:
            self.app.scroll_btn.config(text="■ STOP", bg="#f44336")
            self.run_scroll()

    def run_scroll(self):
        if not self.is_scrolling: return

        wrapper = self.app.output_text
        cols = wrapper.columns

        # 1. Scroll the master
        # Because Col 0 has all text, it won't stop prematurely.
        cols[0].yview_scroll(1, "pixels")

        # 2. Update the slaves based on Col 0's position
        top_pos = cols[0].yview()[0]
        line_count = int(cols[0].index('end-1c').split('.')[0])
        self.app.view_renderer.scroll_offset = top_pos * line_count

        if len(cols) > 1:
            self.app.view_renderer.render_slaves_only()

        # # 3. Stop-check: Only look at the VERY LAST column
        # last_col = cols[-1]
        # # Check if the last column has actually reached the end of the lines list
        # if self.app.view_renderer.scroll_offset + (
        #         len(cols) * self.app.view_renderer._get_visible_rows_count()) >= line_count:
        #     # Final check if the last line is visible in the last widget
        #     if last_col.dlineinfo("end-1c"):
        #         # (Pas hier de eerder besproken pixel-check toe)
        #         self.stop_scroll()
        #         return

        speed = self.app.speed_slider.get()
        delay = max(1, int(210 - (speed * 2)))
        self._scroll_job = self.root.after(delay, self.run_scroll)

class ChordProConverter:
    """
    Handles the logical transformation of song data.
    Responsible for transposing, converting between formats, and syntax detection.
    """

    def __init__(self):
        self.notes_sharp = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        self.map_to_sharp = {'Db': 'C#', 'Eb': 'D#', 'Gb': 'F#', 'Ab': 'G#', 'Bb': 'A#', 'Cb': 'B', 'Fb': 'E'}

    def transpose_logic(self, text, delta):
        """
        Transposes chords within a text string by a given number of semitones.
        Improved with word boundaries to prevent corrupting normal words.
        """
        # Added \b at the start to ensure we only catch standalone chords
        # and not the first letter of words like 'chords' or 'All'
        chord_pattern = r'\b([A-G][#b]?)(m|maj|min|dim|aug|sus|add|alt|[\d/]*)'

        def replace_chord(match):
            full_root = match.group(1)
            suffix = match.group(2)

            # Normalize to sharp for indexing
            root = self.map_to_sharp.get(full_root, full_root)

            if root in self.notes_sharp:
                current_idx = self.notes_sharp.index(root)
                new_idx = (current_idx + delta) % 12
                # Return transposed root + the original suffix
                return self.notes_sharp[new_idx] + suffix

            return match.group(0)

        # We only want to transpose lines that are actually chord lines
        # to avoid accidental hits in lyrics.
        lines = text.splitlines()
        transposed_lines = []

        for line in lines:
            if self.is_chord_line(line) or line.startswith('.'):
                transposed_lines.append(re.sub(chord_pattern, replace_chord, line))
            else:
                # If it's a lyric line, leave it exactly as it is
                transposed_lines.append(line)

        return "\n".join(transposed_lines)

    def is_chord_line(self, line):
        """
        Heuristic check to determine if a line consists primarily of music chords.
        """
        # Remove common delimiters/punctuation to isolate potential chord names
        clean = re.sub(r'[|*:\;!?\[\]\(\)]', ' ', line).strip()
        if not clean:
            return False

        words = clean.split()
        # Pattern for standard music notation and complex extensions
        pattern = r'^[A-G][b#]?(?:maj|min|m|M|dim|aug|sus|add|alt|dim|[\d/])*$'

        chords = [w for w in words if re.match(pattern, w, re.IGNORECASE)]

        # Line is a chord line if at least 60% of words match the pattern
        return len(chords) > 0 and len(chords) >= len(words) * 0.6

    def chordpro_to_plain(self, chordpro_text):
        """
        Converts ChordPro format (embedded brackets) to plain text (chords above lyrics).
        """
        lines = chordpro_text.splitlines()
        output = []

        for line in lines:
            # Skip metadata tags (handled by UI entries)
            if line.startswith('{title:') or line.startswith('{artist:') or not line.strip():
                if not line.strip(): output.append("")
                continue

            # Convert structural tags to readable headers
            comment_match = re.search(r'\{(.*?)\}', line)
            if comment_match:
                content = comment_match.group(1).strip()
                if "start_of_chorus" in content.lower():
                    output.append("[Chorus]")
                elif "end_of_chorus" in content.lower():
                    pass
                else:
                    clean = re.sub(r'^(comment|c):\s*', '', content, flags=re.IGNORECASE)
                    output.append(f"[{clean}]")
                continue

            # Process embedded chords: [Am]Text -> Am above Text
            chords_found = list(re.finditer(r'\[(.*?)\]', line))
            if chords_found:
                chord_line = [" "] * 200
                text_line = list(re.sub(r'\[.*?\]', '', line))

                offset = 0
                for m in chords_found:
                    chord_text = m.group(1)
                    pos = m.start() - offset
                    for j, char in enumerate(chord_text):
                        if pos + j < len(chord_line):
                            chord_line[pos + j] = char
                    offset += len(m.group(0))

                # Prefix with '.' for the UI renderer to identify chord lines
                output.append("." + "".join(chord_line).rstrip())
                output.append("".join(text_line))
            else:
                output.append(line)

        return "\n".join(output)

    def generate_cho_content(self, input_text, artist, title):
        """
        Converts editor text (chords above lyrics) back to ChordPro format.
        """
        lines = input_text.splitlines()
        cho = [f"{{title: {title}}}", f"{{artist: {artist}}}", ""]
        i, in_chorus = 0, False

        while i < len(lines):
            line = lines[i]

            # 1. Section Header detection
            if re.match(r'^\[.*\]$', line.strip()):
                section = line.strip()[1:-1]
                if in_chorus:
                    cho.append("{end_of_chorus}")
                    in_chorus = False

                if "chorus" in section.lower():
                    cho.append("{start_of_chorus}")
                    in_chorus = True
                else:
                    cho.append(f"{{comment: {section}}}")
                i += 1
                continue

            # 2. Merge chord lines into lyric lines
            is_marker_line = line.startswith('.')
            current_line_val = line[1:] if is_marker_line else line

            if (is_marker_line or self.is_chord_line(line)) and (i + 1 < len(lines)) and not self.is_chord_line(
                    lines[i + 1]):
                chords = [(m.start(), m.group()) for m in re.finditer(r'\S+', current_line_val)]

                next_line = lines[i + 1]
                next_line_val = next_line[1:] if next_line.startswith('.') else next_line
                txt = list(next_line_val)

                # Insert from right to left to prevent index shifting
                for pos, c in reversed(chords):
                    fmt = f"[{c.strip('()[]{}')}]"
                    if pos < len(txt):
                        txt.insert(pos, fmt)
                    else:
                        txt.append(' ' * (pos - len(txt)) + fmt)

                cho.append("".join(txt))
                i += 2
            else:
                # 3. Standalone lines
                if line.strip():
                    if is_marker_line or self.is_chord_line(line):
                        cho.append(re.sub(r'(\S+)', lambda m: f"[{m.group().strip('()[]{}')}]", current_line_val))
                    else:
                        cho.append(current_line_val)
                else:
                    if in_chorus:
                        cho.append("{end_of_chorus}")
                        in_chorus = False
                    cho.append("")
                i += 1

        if in_chorus:
            cho.append("{end_of_chorus}")

        return "\n".join(cho)


class ThemeManager:
    def __init__(self):
        # We use your specific naming convention for the themes
        self.themes = {
            "light": {
                "bg": "#FFFFFF", "fg": "#000000", "chord": "#B38F00", "comment": "#0055AA", "alt": "#0055AA",
                "app_bg": "#F5F5F5",  # Light gray base
                "surface": "#E0E0E0",  # Darker gray for section headers/frames
                "input_bg": "#FFFFFF", "input_fg": "#000000",
                "label_fg": "#444444", "btn_bg": "#DDDDDD", "btn_fg": "black"
            },
            "sepia": {
                "bg": "#F4ECD8", "fg": "#5B4636", "chord": "#A65D00", "comment": "#6D834F", "alt": "#A65D00",
                "app_bg": "#EFE6CF",  # Darker sepia base
                "surface": "#FF0000",  # Deepest sepia for frames
                "input_bg": "#FDF9F0", "input_fg": "#5B4636",
                "label_fg": "#8C6A50", "btn_bg": "#D3C5A3", "btn_fg": "#5B4636"
            },
            "midnight": {
                "bg": "#2C2C2C", "fg": "#E0E0E0", "chord": "#FFD54F", "comment": "#90A4AE", "alt": "#81C784",
                "app_bg": "#121212",  # Deep black base
                "surface": "#1E1E1E",  # Slightly lighter surface for frames
                "input_bg": "#333333", "input_fg": "#FFFFFF",
                "label_fg": "#4DB6AC",  # Teal accent for labels
                "btn_bg": "#404040", "btn_fg": "#E0E0E0"
            },
            "dark": {
                "bg": "#000000", "fg": "#FFFFFF", "chord": "#ffcc00", "comment": "#64B5F6", "alt": "#88CCFF",
                "app_bg": "#1A1A1A",  # Dark gray base
                "surface": "#2A2A2A",  # Mid-gray for frames
                "input_bg": "#000000", "input_fg": "#FFFFFF",
                "label_fg": "#FF8A65",  # Soft orange accent for labels
                "btn_bg": "#333333", "btn_fg": "white"
            }
        }
        self.current_theme_name = "light"
        self.action_colors = [
            "#ffd700", "#17499e", "#f44336", "#4caf50", "#444444",
            "#607d8b", "#9e9e9e", "#9c27b0", "#2196f3", "#e91e63", "#ff9800"
        ]

    def set_theme(self, theme_name):
        """
        Updates the current theme name if it exists in the dictionary.
        This is called by load_settings.
        """
        if theme_name in self.themes:
            self.current_theme_name = theme_name
            return True
        return False

    def update_button_text(self, theme_button):
        """
        Synchronizes the theme button text with the current state.
        Call this after loading settings or during initialization.
        """
        names = list(self.themes.keys())
        try:
            idx = names.index(self.current_theme_name)
        except ValueError:
            idx = 0

        next_idx = (idx + 1) % len(names)

        current_display = self.current_theme_name.replace("_", " ").upper()
        next_display = names[next_idx].replace("_", " ").upper()

        theme = self.themes[self.current_theme_name]

        theme_button.config(
            text=f"🎨 {current_display} ➔ {next_display}",
            bg=theme["btn_bg"],
            fg=theme["btn_fg"]
        )

    def toggle_theme(self, app):
        """Cycles to the next theme and applies it."""
        names = list(self.themes.keys())
        idx = (names.index(self.current_theme_name) + 1) % len(names)
        self.current_theme_name = names[idx]

        # Apply the changes
        self.apply_theme(app)

        # Update the button text (moved logic here)
        next_idx = (idx + 1) % len(names)
        current_display = self.current_theme_name.replace("_", " ").upper()
        next_display = names[next_idx].replace("_", " ").upper()
        self.update_button_text(app.theme_btn)

    def apply_theme(self, app):
        """Main entry point for theme application."""
        theme = self.themes[self.current_theme_name]
        app.root.config(bg=theme["app_bg"])

        # Start the recursive layering process
        self._apply_to_widget_recursive(app.root, theme, app)

        # Workaround for specific frames
        if hasattr(app.ui_manager, 'view_frame'):
            app.ui_manager.view_frame.config(fg=theme["label_fg"], bg=theme["app_bg"])

        app.output_text.apply_layout_params(theme, app.font_size)

    def _apply_to_widget_recursive(self, widget, theme, app, is_inside_container=False):
        """Your layered coloring logic, now encapsulated in the manager."""
        w_type = widget.winfo_class()
        bg_color = theme["surface"] if is_inside_container else theme["app_bg"]

        # --- Logic for Frames ---
        if w_type in ("Frame", "LabelFrame"):
            current_surface = theme["surface"] if w_type == "LabelFrame" else bg_color
            widget.config(bg=current_surface)
            if w_type == "LabelFrame":
                widget.config(fg=theme["label_fg"], font=("Arial", 10, "bold"))

            # Recurse into children
            for child in widget.winfo_children():
                self._apply_to_widget_recursive(child, theme, app, is_inside_container=(w_type == "LabelFrame"))

        # --- Logic for Labels ---
        elif w_type == "Label":
            widget.config(bg=widget.master.cget("bg"), fg=theme["label_fg"])

        # --- Logic for Text/Entry ---
        elif w_type in ("Entry", "Text"):
            if widget == app.output_text:
                widget.config(bg=theme["bg"], fg=theme["fg"], insertbackground=theme["fg"])
                # Syntax Highlighting
                self._update_text_tags(widget, theme, app.font_size)
            else:
                widget.config(bg=theme["input_bg"], fg=theme["input_fg"],
                              insertbackground=theme["input_fg"], relief=tk.FLAT)

        # --- Logic for Buttons/Radio ---
        elif w_type in ("Button", "Radiobutton"):
            try:
                current_bg = str(widget.cget("bg")).lower()
            except:
                current_bg = ""

            if current_bg not in self.action_colors:
                if w_type == "Radiobutton":
                    widget.config(bg=widget.master.cget("bg"), fg=theme["label_fg"],
                                  selectcolor=theme["input_bg"], activebackground=theme["surface"])
                else:
                    widget.config(bg=theme["btn_bg"], fg=theme["btn_fg"], relief=tk.RAISED)

        # --- Logic for Scales ---
        elif w_type == "Scale":
            widget.config(bg=widget.master.cget("bg"), fg=theme["label_fg"],
                          troughcolor=theme["input_bg"], highlightthickness=0)

        # If not a frame, we still need to check children for standalone widgets
        if w_type not in ("Frame", "LabelFrame"):
            for child in widget.winfo_children():
                self._apply_to_widget_recursive(child, theme, app, is_inside_container)

    def _update_text_tags(self, text_widget, theme, font_size):
        """Handles the critical syntax highlighting colors."""
        # If text_widget is actually our wrapper, use the new method
        if hasattr(text_widget, 'apply_layout_params'):
            text_widget.apply_layout_params(theme, font_size)
        else:
            for t in ["chord", "comment", "normal", "alt_move"]:
                text_widget.tag_delete(t)

            text_widget.tag_config("normal", foreground=theme["fg"])
            text_widget.tag_config("chord", foreground=theme["chord"])
            text_widget.tag_config("comment", foreground=theme["comment"], font=("Arial", font_size, "italic"))
            text_widget.tag_config("alt_move", foreground=theme["alt"])

            text_widget.tag_raise("chord")
            text_widget.tag_raise("comment")
            text_widget.tag_lower("normal")


class UIManager:
    def __init__(self, app):
        self.app = app
        self.root = app.root

        # Container voor alle elementen die we aan/uit willen zetten
        self.ui_elements = []

    def setup_ui(self):
        """Bouwt de volledige interface op."""
        self._setup_top_panel()
        self._setup_editor_panel()
        self._setup_viewer_settings_panel()
        self._setup_output_panel()

    def _setup_top_panel(self):
        """Sectie 1: Artist, Title en Bestandsacties."""
        self.top_frame = tk.Frame(self.root)
        self.top_frame.pack(pady=10, padx=20, fill=tk.X)
        self.ui_elements.append(self.top_frame)

        # Meta data (Artist/Title)
        self.meta_frame = tk.Frame(self.top_frame)
        self.meta_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(self.meta_frame, text="Artist:").grid(row=0, column=0, sticky="w")
        self.app.artist_entry = tk.Entry(self.meta_frame, font=("Arial", 10))
        self.app.artist_entry.grid(row=0, column=1, sticky="ew", padx=5)

        tk.Label(self.meta_frame, text="Title:").grid(row=1, column=0, sticky="w")
        self.app.title_entry = tk.Entry(self.meta_frame, font=("Arial", 10))
        self.app.title_entry.grid(row=1, column=1, sticky="ew", padx=5)
        self.meta_frame.columnconfigure(1, weight=1)

        # Buttons
        self.file_btn_frame = tk.Frame(self.top_frame)
        self.file_btn_frame.pack(side=tk.RIGHT, padx=(20, 0))

        btns = [
            ("OPEN", self.app.open_file, "#FFD700", "black"),
            ("SAVE", self.app.convert_and_save, "#17499E", "white"),
            ("CLEAR", self.app.clear_fields, "#f44336", "white"),
            ("NEXT ⏩", self.app.next_song, "#4CAF50", "white")
        ]
        for txt, cmd, bg, fg in btns:
            tk.Button(self.file_btn_frame, text=txt, command=cmd, bg=bg, fg=fg, width=8).pack(side=tk.LEFT, padx=2)

    def _setup_editor_panel(self):
        """Sectie 2: De tekstverwerker."""
        self.editor_frame = tk.Frame(self.root)
        self.editor_frame.pack(padx=20, fill=tk.BOTH, expand=True)
        self.ui_elements.append(self.editor_frame)

        tk.Label(self.editor_frame, text="SONG EDITOR", font=("Arial", 9, "bold")).pack(anchor="w")

        editor_container = tk.Frame(self.editor_frame)
        editor_container.pack(fill=tk.BOTH, expand=True)

        self.app.input_text = tk.Text(editor_container, wrap=tk.NONE, height=10, font=("Courier New", 11), undo=True)
        self.app.input_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.app.input_scroll = tk.Scrollbar(editor_container, orient="vertical", command=self.app.input_text.yview,
                                             width=35)
        self.app.input_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.app.input_text.config(yscrollcommand=self.app.input_scroll.set)

        # Editor Toolbar
        self.edit_tools = tk.Frame(self.editor_frame)
        self.edit_tools.pack(fill=tk.X, pady=5)

        tk.Label(self.edit_tools, text="  Transpose:").pack(side=tk.LEFT)
        tk.Button(self.edit_tools, text="♭", command=lambda: self.app.transpose_chords(-1), width=3, bg="#444444",
                  fg="white").pack(side=tk.LEFT, padx=2)
        tk.Button(self.edit_tools, text="♯", command=lambda: self.app.transpose_chords(1), width=3, bg="#444444",
                  fg="white").pack(side=tk.LEFT, padx=2)

        tk.Button(self.edit_tools, text="🔄 UPDATE PREVIEW", command=self.app.test_conversion, bg="#607D8B", fg="white",
                  font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT)

        self.app.undo_btn = tk.Button(self.edit_tools, text="↩ RESTORE PREVIOUS", command=self.app.undo_editor,
                                      bg="#9E9E9E", fg="white", state=tk.DISABLED)
        self.app.undo_btn.pack(side=tk.LEFT, padx=5)

    def _setup_viewer_settings_panel(self):
        """Sectie 3: Instellingen voor de weergave."""
        self.view_frame = tk.LabelFrame(self.root, text=" Viewer Settings ", padx=10, pady=5)
        self.view_frame.pack(padx=20, pady=5, fill=tk.X)

        # Row 1 (Modes & Theme)
        row1 = tk.Frame(self.view_frame)
        row1.pack(fill=tk.X, pady=2)

        self.app.view_btn = tk.Button(row1, text="🖥 VIEW MODE", command=self.app.toggle_view_mode, bg="#9C27B0",
                                      fg="white", font=("Arial", 11, "bold"), height=2)
        self.app.view_btn.pack(side=tk.LEFT, padx=5)

        self.app.fs_btn = tk.Button(row1, text="📺 FULL SCREEN", command=self.app.toggle_fullscreen, bg="#2196F3",
                                    fg="white", font=("Arial", 11), height=2)
        self.app.fs_btn.pack(side=tk.LEFT, padx=5)

        self.app.perf_btn = tk.Button(row1, text="🎭 PERF MODE", command=self.app.enter_performance_mode, bg="#E91E63",
                                      fg="white", font=("Arial", 10, "bold"), height=2)
        self.app.perf_btn.pack(side=tk.LEFT, padx=5)

        self.app.theme_btn = tk.Button(row1, text="🌓 LIGHT", command=self.app.toggle_theme, width=16, height=2)
        self.app.theme_btn.pack(side=tk.LEFT, padx=5)

        # Row 2 (Scrolling & Layout)
        row2 = tk.Frame(self.view_frame)
        row2.pack(fill=tk.X, pady=5)

        self.app.scroll_btn = tk.Button(row2, text="▶ START", command=self.app.toggle_scroll, bg="#FF9800", width=12,
                                        height=2, font=("Arial", 10, "bold"))
        self.app.scroll_btn.pack(side=tk.LEFT, padx=5)

        self.app.speed_slider = tk.Scale(row2, from_=1, to=100, orient=tk.HORIZONTAL, showvalue=False, width=25)
        self.app.speed_slider.set(20)
        self.app.speed_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        for text, mode in [("1", "one"), ("N", "two"), ("Auto", "auto")]:
            tk.Radiobutton(row2, text=text, variable=self.app.column_mode, value=mode,
                           command=lambda m=mode: self.app.output_text.set_column_mode(m),
                           indicatoron=0, width=5, height=2).pack(side=tk.LEFT, padx=1)

    def _setup_output_panel(self):
        """
        Setup the output panel with a persistent scrollbar
        and a dedicated container for text columns.
        """
        # 1. The main stable container
        self.app.viewer_main_frame = tk.Frame(self.app.root, bg='#1e1e1e')
        self.app.viewer_main_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # 2. Create the scrollbar in the main container
        self.output_scrollbar = tk.Scrollbar(
            self.app.viewer_main_frame,
            orient=tk.VERTICAL,
            width=25
        )
        self.output_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 3. Create a SUB-FRAME for the text columns only
        #  This is what the OutputWrapper will manage (and clear)
        self.column_container = tk.Frame(self.app.viewer_main_frame, bg='#1e1e1e')
        self.column_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 4. Initialize Wrapper pointing to the SUB-FRAME
        self.app.output_text = OutputWrapper(
            self.app,
            self.column_container,  #  Point to the sub-frame!
            ("DejaVu Sans Mono", self.app.font_size, "bold")
        )

        # 5. Connect scrollbar to wrapper
        self.output_scrollbar.config(command=self.app.output_text.sync_yview)
        self.app.output_text.scrollbar = self.output_scrollbar
        self.output_text = self.app.output_text

    def refresh_layout(self, is_view_mode):
        """Verbergt of toont frames op basis van de huidige mode."""
        if is_view_mode:
            self.top_frame.pack_forget()
            self.editor_frame.pack_forget()
        else:
            self.top_frame.pack(pady=10, padx=20, fill=tk.X)
            self.editor_frame.pack(padx=20, fill=tk.BOTH, expand=True)
            # Zorg dat de viewer frames altijd onderaan blijven staan
            self.view_frame.pack(padx=20, pady=5, fill=tk.X)
            self.viewer_main_frame.pack(padx=20, pady=(0, 10), fill=tk.BOTH, expand=True)


class Song:
    def __init__(self, artist="", title="", content="", file_path=None):
        self.artist = artist
        self.title = title
        self.content = content
        self.file_path = file_path

    @classmethod
    def from_file(cls, file_path, converter):
        """Creates a Song object from a file."""
        with open(file_path, 'r', encoding='utf-8') as f:
            raw_content = f.read()

        # Metadata extraction
        title_match = re.search(r'\{(?:title|t):\s*(.*)\}', raw_content, re.IGNORECASE)
        artist_match = re.search(r'\{(?:artist|a):\s*(.*)\}', raw_content, re.IGNORECASE)

        title = title_match.group(1).strip() if title_match else "Unknown Title"
        artist = artist_match.group(1).strip() if artist_match else "Unknown Artist"

        # Convert to plain text for editor
        plain_text = converter.chordpro_to_plain(raw_content)

        return cls(artist=artist, title=title, content=plain_text)


class ViewRenderer:
    def __init__(self, app):
        self.app = app
        # The main container where we will place our columns
        self.container = app.viewer_main_frame
        self.columns = []  # List to keep track of created text widgets
        self.multi = False # indicates if last display is spread over multiple columns yes/no
        self.scroll_offset = 0.0  # offset for scrolling

    def render_slaves_only(self):
        """
        Uses the actual visible range of the first column
        to determine where the next columns should start.
        """
        lines = self._parse_to_lines(self.app.last_chordpro_data)
        cols = self.app.output_text.columns
        if len(cols) < 2: return

        # 1. Haal de LAATSTE zichtbare regel van de eerste edit op
        # '@0,height' gives the index of the character at the bottom-left
        last_visible_idx = cols[0].index(f"@0,{cols[0].winfo_height()}")
        last_line_in_col1 = int(last_visible_idx.split('.')[0])

        # 2. Bepaal het startpunt voor de volgende kolommen
        # We subtract the overlap here to ensure the transition is smooth
        overlap_count = 2
        base_start_for_col2 = last_line_in_col1 - overlap_count

        # 3. Vul de slave-kolommen
        rows_per_col = self._get_visible_rows_count()  # Gebruik dit voor de lengte van de chunk

        for i in range(1, len(cols)):
            txt = cols[i]
            txt.config(state=tk.NORMAL)
            txt.delete("1.0", tk.END)

            # Calculate slice for this column
            start_idx = base_start_for_col2 + ((i - 1) * (rows_per_col - overlap_count))

            # Voeg de overlap toe in rood
            overlap_chunk = lines[start_idx: start_idx + overlap_count]
            for text, tag in overlap_chunk:
                txt.insert(tk.END, text + "\n", "overlap_red")

            # Voeg de rest toe in normaal
            main_start = start_idx + overlap_count
            main_chunk = lines[main_start: main_start + rows_per_col]
            for text, tag in main_chunk:
                txt.insert(tk.END, text + "\n", tag if tag else "normal")

            txt.config(state=tk.DISABLED)

    def render_scrolled_content(self):
        """
        Fills the master column with all text PLUS padding
        to allow scrolling until the very last line is visible in the last column.
        """
        lines = self._parse_to_lines(self.app.last_chordpro_data)
        cols = self.app.output_text.columns

        # --- MASTER (Edit 1) ---
        cols[0].config(state=tk.NORMAL)
        cols[0].delete("1.0", tk.END)

        # Insert all actual lines
        for text, tag in lines:
            cols[0].insert(tk.END, text + "\n", tag if tag else "normal")

        # ADD PADDING. We add a full page of empty lines
        # so the widget can scroll much further than the text itself.
        rows_per_col = self._get_visible_rows_count()
        for _ in range(rows_per_col + 5):
            cols[0].insert(tk.END, "\n")

        cols[0].config(state=tk.DISABLED)

        # --- SLAVES (Edit 2+) ---
        self.render_slaves_only()

    def render(self, content=None):
        """
        Renders content into columns, deferring layout decisions to the OutputWrapper.
        """
        self.app.root.update_idletasks()

        if not content:
            content = self.app.last_chordpro_data if hasattr(self.app, 'last_chordpro_data') else ""
        self.app.last_chordpro_data = content

        lines = self._parse_to_lines(content)

        # ONLY ask the wrapper. It knows if it should be 'auto', 'one' or 'forced multi'.
        num_columns = self.app.output_text.get_target_column_count(lines)

        # Rebuild the physical widgets
        cols = self.app.output_text.rebuild(num_columns)

        # 2. Split lines into chunks based on the ACTUAL columns we just built
        rows = (len(lines) + num_columns - 1) // num_columns
        chunks = [lines[i:i + rows] for i in range(0, len(lines), rows)]

        # 3. Fill the columns
        self.multi = (num_columns > 1)  # Simpler check for multi-column state

        for i, txt in enumerate(cols):
            # Basic bindings are already handled in OutputWrapper.rebuild()
            # but if you need extra renderer-specific logic, do it here.

            if i < len(chunks):
                txt.config(state=tk.NORMAL)
                txt.delete("1.0", tk.END)  # Ensure it's empty
                for text, tag in chunks[i]:
                    txt.insert(tk.END, text + "\n", tag if tag else "normal")
                txt.config(state=tk.DISABLED)

    def _get_visible_rows_count(self):
        """
        Calculates how many lines of text fit into the current
        height of the text widget based on the font size.
        """
        # Use the first column to measure (they are all equal height)
        if not self.app.output_text.columns:
            return 20

        txt_widget = self.app.output_text.columns[0]
        self.app.root.update_idletasks()

        # Use dlineinfo to get the exact height of a single line
        # If the widget is empty, we fall back to a font-based estimate
        line_info = txt_widget.dlineinfo("1.0")
        if line_info:
            line_height = line_info[3]  # Index 3 is the height of the bounding box
        else:
            line_height = self.app.font_size * 1.45  # Fallback multiplier

        pixel_height = txt_widget.winfo_height()
        return int(pixel_height // line_height)

    def _calculate_dynamic_columns(self, lines):
        """Standard safe calculation."""
        pixel_width = self.container.winfo_width()
        if pixel_width < 100: return 1

        char_width = self.app.font_size * 0.75
        max_line_len = max([len(l[0]) for l in lines]) if lines else 0

        # Simple math: how many 'max_lines' fit side by side?
        fitted_cols = int(pixel_width // (max_line_len * char_width + 20))
        return max(1, min(4, fitted_cols))

    def _parse_to_lines(self, content):
        """Converts ChordPro content to a list of (text, tag) for rendering."""
        rendered_lines = []
        for line in content.splitlines():
            # Skip metadata tags
            if any(line.startswith(tag) for tag in ['{title:', '{t:', '{artist:', '{a:']):
                continue

            # Handle internal markers
            if line.startswith('.'):
                rendered_lines.append((line[1:], "chord"))
                continue

            # Process Comments / Chorus markers
            comment_match = re.search(r'\{(.*?)\}', line)
            if comment_match:
                rendered_lines.append((self._format_comment(comment_match.group(1)), "comment"))
                continue

            # Process Embedded chords (e.g., Hey [D] Jude)
            if '[' in line and ']' in line:
                chord_line, lyric_line = self._split_chords_and_lyrics(line)
                rendered_lines.append((chord_line, "chord"))
                rendered_lines.append((lyric_line, None))
            else:
                rendered_lines.append((line, None))
        return rendered_lines

    def _format_comment(self, c_content):
        """Formats {comment: Chorus} -> (Chorus)."""
        c_content = c_content.strip().lower()
        if "chorus" in c_content:
            return "--- CHORUS ---" if "start" in c_content else "--------------"
        clean_val = re.sub(r'^(comment|c|title|artist|t|a):\s*', '', c_content, flags=re.IGNORECASE)
        return f"({clean_val})"

    def _split_chords_and_lyrics(self, line):
        """Logic to split embedded chords into separate lines (chords above lyrics)."""
        chord_line = [" "] * 150
        lyric_line = []
        current_pos = 0
        parts = re.split(r'(\[.*?\])', line)
        for part in parts:
            if part.startswith('[') and part.endswith(']'):
                chord_text = part[1:-1]
                for j, char in enumerate(chord_text):
                    if current_pos + j < len(chord_line): chord_line[current_pos + j] = char
            else:
                lyric_line.append(part)
                current_pos += len(part)
        return "".join(chord_line).rstrip(), "".join(lyric_line)

    def _draw_single_column(self, lines):
        """Standard vertical rendering."""
        for text, tag in lines:
            self.output_text.insert(tk.END, text + "\n", tag if tag else "normal")

class ChoConverterApp:
    def __init__(self, root):
        self.root = root

        self.root.title("ChordPro Tool - Converter & Viewer")
        self.root.geometry("1000x900")

        # 1. Start managers
        self.ui_manager = UIManager(self)
        self.perf_manager = PerformanceManager(self)
        self.converter = ChordProConverter()
        self.theme_manager = ThemeManager()

        # 2. State Variables
        self.font_size = 14
        self.is_view_mode = False
        self.column_mode = tk.StringVar(value="auto")
        self.is_fullscreen = False
        self.editor_history = ""
        self.current_editor_state = ""
        self.ui_elements = []
        self.is_performance_mode = False
        self.current_playlist = []  # List of files from the active tag
        self.current_index = -1  # Current position within the list
        self.click_timer = None
        self.chord_explanations = CHORD_EXPLANATIONS

        self.settings_file = "settings.json"

        # Default theme name
        self.current_theme_name = "light"

        self.notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

        self.current_song = Song()

        # 3. Build UI
        self.ui_manager.setup_ui()

        self.view_renderer = ViewRenderer(self)

        # 4. Bindings & Init
        self.setup_bindings()
        self.load_settings()
        self._apply_theme()

    def setup_touch_scroll(self, widget):
        """Enables swipe-scrolling functionality for the given widget."""
        widget.bind("<Button-1>", self.on_touch_start)
        widget.bind("<B1-Motion>", lambda e: self.on_touch_drag(e, widget))

    def on_touch_start(self, event):
        """Captures the initial touch coordinates."""
        self.touch_start_y = event.y

    def on_touch_drag(self, event, widget):
        """Calculates movement delta and scrolls the widget accordingly."""
        delta = self.touch_start_y - event.y
        # Scroll the widget (higher divisor results in slower/smoother scrolling)
        widget.yview_scroll(int(delta / 10), "units")
        # Update start position for fluid motion
        self.touch_start_y = event.y

    def transpose_chords(self, delta):
        """
        Transposes chords without symbol stacking (e.g., A###).
        Converts everything to the most logical sharp/flat note.
        """
        current_text = self.input_text.get("1.0", tk.END)
        new_text = self.converter.transpose_logic(current_text, delta)
        self.input_text.delete("1.0", tk.END)
        self.input_text.insert(tk.END, new_text)
        self.test_conversion()


    def show_chord_info(self, event):
        """Displays a context menu with chord explanations when triggered."""
        # 'event.widget' is the specific tk.Text column that was clicked
        text_widget = event.widget

        # Pass this specific widget to your manager
        ChordInfoManager().show_menu(self.root, text_widget, event)

    def open_file(self, file_path=None, playlist=None):
        """Opens a file and optionally stores the surrounding playlist context."""
        if file_path is None:
            # Open the selection library if no specific path is provided
            TouchFileList(self.root, self.open_file, self)
            return

        # If a playlist is provided from the library, store it for navigation
        if playlist is not None:
            self.current_playlist = playlist
            try:
                self.current_index = self.current_playlist.index(file_path)
            except ValueError:
                self.current_index = -1

        self.current_song = Song.from_file(file_path, self.converter)
        self.current_song.file_path = file_path

        # UI updaten vanuit het object
        self.artist_entry.delete(0, tk.END)
        self.artist_entry.insert(0, self.current_song.artist)
        self.title_entry.delete(0, tk.END)
        self.title_entry.insert(0, self.current_song.title)

        self.input_text.delete("1.0", tk.END)
        self.input_text.insert(tk.END, self.current_song.content)

        self.current_editor_state = self.current_song.content
        self._sync_and_render()

    def load_settings(self):
        """Loads user preferences (theme, last category, sorting) from JSON."""
        self.settings_file = "settings.json"
        # Defaults
        theme_to_apply = "light"
        self.active_tag = "All"
        self.sort_song_by = "none"

        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    theme_to_apply = settings.get("theme", "light")
                    self.active_tag = settings.get("last_category", "All")
                    self.sort_song_by = settings.get("last_sort", "none")
            except Exception as e:
                print(f"Error loading settings: {e}")  # Standardized logging
                self._set_defaults()
        else:
            self._set_defaults()

        # Apply the loaded theme via the manager
        # We update the manager's state and then apply it to the UI
        self.current_theme_name = theme_to_apply
        self.theme_manager.set_theme(theme_to_apply)
        self.theme_manager.update_button_text(self.theme_btn)
        self._apply_theme()

    def toggle_theme(self):
        """Callback for the theme button."""
        # The manager handles the logic, cycling, and applying
        self.theme_manager.toggle_theme(self)
        self.current_theme_name = self.theme_manager.current_theme_name

        # The app handles persistence and refreshing the view
        self.save_settings()
        self._sync_and_render()

    def _apply_theme(self):
        """Initial theme application on startup."""
        self.theme_manager.apply_theme(self)

    def _set_defaults(self):
        """Sets default values if no settings file exists."""
        self.current_theme_name = "light"
        self.active_tag = "All"
        self.sort_song_by = "none"

    def save_settings(self):
        """Saves current state to the settings file."""
        settings = {
            "theme": self.current_theme_name,
            "last_category": self.active_tag,
            "last_sort": self.sort_song_by
        }
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def _sync_and_render(self):
        """
        Central helper to bridge UI data with the logic converter and update the view.
        Prevents code duplication across font changes, undo, and song switching.
        """
        # 1. Gather data from UI
        self.current_song.artist = self.artist_entry.get().strip()
        self.current_song.title = self.title_entry.get().strip()
        self.current_song.content = self.input_text.get("1.0", "end-1c")

        # 2. Process through logic class
        res = self.converter.generate_cho_content(
            self.current_song.content,
            self.current_song.artist,
            self.current_song.title
        )

        # 3. Update the presenter view
        self.render_view(content=res)

        # Return the result in case the calling function needs it (like for saving)
        return res

    def change_font(self, delta):
        """Adjusts font size and triggers a re-render to update layout calculations."""
        self.font_size += delta
        # Apply updated font to tags
        self.output_text.configure(font=("Courier New", self.font_size, "bold"))
        self.output_text.tag_configure("comment", font=("Arial", self.font_size, "italic"))

        # Re-render view to recalculate column distributions with new size
        self._sync_and_render()

    def toggle_view_mode(self):
        """Switches the UI between Editor (Edit) and Presenter (View) modes."""
        if not self.is_view_mode:
            # --- SWITCH TO VIEW MODE ---
            # Hide all main UI elements to clear the screen
            for el in self.ui_elements:
                el.pack_forget()

            # Ensure the viewer frames are visible
            self.ui_manager.view_frame.pack(padx=20, pady=5, fill=tk.X)
            self.viewer_main_frame.pack(padx=20, pady=10, fill=tk.BOTH, expand=True)

            self.view_btn.config(text="🔙 EDIT MODE", bg="#607D8B")
            self.is_view_mode = True

            # Display the container including text and the wide scrollbar
            self.viewer_main_frame.pack(padx=20, pady=10, fill=tk.BOTH, expand=True)
        else:
            # --- SWITCH BACK TO EDIT MODE ---
            if hasattr(self, 'exit_perf_btn'): self.exit_perf_btn.destroy()

            # Hide viewer elements
            self.viewer_main_frame.pack_forget()
            self.ui_manager.view_frame.pack_forget()

            # Restore editor components to the layout
            self.ui_manager.top_frame.pack(pady=10, padx=20, fill=tk.X)
            self.ui_manager.editor_frame.pack(padx=20, fill=tk.BOTH, expand=True)

            # Re-add controls and viewer at the bottom of the editor
            self.ui_manager.view_frame.pack(padx=20, pady=5, fill=tk.X)
            self.viewer_main_frame.pack(padx=20, pady=(0, 10), fill=tk.BOTH, expand=True)

            self.view_btn.config(text="🖥 VIEW MODE", bg="#9C27B0")
            self.is_view_mode = False

    def enter_performance_mode(self):
        """Optimizes the screen for live performance by removing all distractions."""
        self.perf_manager.enter_performance_mode()


    def render_view(self, content=None):
        """Converts internal data to formatted view with column layouts."""
        self.view_renderer.render(content)


    def convert_and_save(self):
        """Generates the .cho file and saves it to disk."""
        artist, title = self.artist_entry.get().strip(), self.title_entry.get().strip()
        if not artist or not title:
            messagebox.showwarning("Error", "Please fill in Artist and Title before saving.")
            return

        res = self._sync_and_render()

        if self.current_song.file_path:
            # Option A: Always overwrite existing file
            fname = self.current_song.file_path
        else:
            # Option B: Save to file using standardized naming convention
            fname = f"{artist.replace(' ', '_')}-{title.replace(' ', '_')}.cho"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(res)

        # Sync and refresh viewer
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert(tk.END, res)
        self.render_view(content=res)

        self.root.title("ChordPro Tool - Saved!")
        messagebox.showinfo("Saved", f"File '{fname}' has been saved successfully.")

    def select_all(self, widget):
        """Helper to select all text within a widget."""
        # Find out the active widget
        widget = self.root.focus_get()
        # Check if it is a text-widget
        if isinstance(widget, (tk.Text, tk.Entry)):
            widget.tag_add("sel", "1.0", "end")
            widget.mark_set("insert", "1.0")  # Move cursor to start
            return "break"  # No typing of standard character


    def clear_fields(self):
        """Resets the UI fields and stops any active scrolling."""
        for w in [self.artist_entry, self.title_entry, self.input_text, self.output_text]:
            if isinstance(w, tk.Entry):
                w.delete(0, tk.END)
            else:
                w.delete("1.0", tk.END)
        if self.is_scrolling: self.toggle_scroll()

    def test_conversion(self):
        """Refreshes the viewer and saves a history snapshot for Undo."""
        new_content = self.input_text.get("1.0", "end-1c")

        # Handle history management for the undo function
        if hasattr(self, 'current_editor_state'):
            if new_content != self.current_editor_state:
                self.editor_history = self.current_editor_state
                self.undo_btn.config(state=tk.NORMAL, bg="#E91E63")
        else:
            self.editor_history = new_content

        self.current_editor_state = new_content

        # Process conversion
        self._sync_and_render()
        self.root.title("ChordPro Tool - Preview Updated")

    def undo_editor(self):
        """Swaps the current editor content with the last saved state."""
        if self.editor_history is not None:
            current_in_editor = self.input_text.get("1.0", "end-1c")

            self.input_text.delete("1.0", tk.END)
            self.input_text.insert(tk.END, self.editor_history)

            # Store current as history (acts like a Redo if pressed again)
            self.editor_history = current_in_editor
            self.current_editor_state = self.input_text.get("1.0", "end-1c")

            # Immediately update the preview
            self._sync_and_render()

    def toggle_fullscreen(self):
        """Toggles XL text display and window-level fullscreen."""
        if not self.is_fullscreen:
            # Enter Full Screen
            self.is_fullscreen = True
            self.old_font_size = self.font_size

            self.root.attributes("-fullscreen", True)

            # Scale font for stage visibility (4x increase)
            self.font_size = self.font_size * 4
            self.output_text.configure(font=("Courier New", self.font_size, "bold"))

            # Auto-adjust scroll speed for larger text
            current_speed = self.speed_slider.get()
            new_speed = min(100, int(current_speed * 1.5))
            self.speed_slider.set(new_speed)

            # Position controls at bottom in front of text
            self.ui_manager.view_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)
            self.ui_manager.view_frame.tkraise()

            self.fs_btn.config(text="🖥 EXIT FULL", bg="#f44336")

            if not self.is_view_mode:
                self.toggle_view_mode()
        else:
            # Exit Full Screen
            self.is_fullscreen = False
            self.root.attributes("-fullscreen", False)

            self.font_size = self.old_font_size
            self.output_text.configure(font=("Courier New", self.font_size, "bold"))

            # Restore original speed
            current_speed = self.speed_slider.get()
            original_speed = max(1, int(current_speed * (2 / 3)))
            self.speed_slider.set(original_speed)

            self.fs_btn.config(text="📺 FULL SCREEN", bg="#2196F3")

    def toggle_scroll(self):
        """Toggles the autoscroll feature with a 10-second countdown delay."""
        self.perf_manager.toggle_scroll()

    def next_song(self):
        """Loads the next song in the playlist and forces a UI refresh (ChromeOS optimized)."""
        if not self.current_playlist:
            return

        self.current_index += 1
        if self.current_index >= len(self.current_playlist):
            self.current_index = 0

        next_file = self.current_playlist[self.current_index]

        # 1. Open and parse file
        self.open_file(next_file)

        # 2. Trigger fresh conversion for presentation
        self._sync_and_render()

        # 4. Force graphical update - Essential for Chromebooks while in fullscreen
        self.root.update_idletasks()

        # Reset scroll position to top
        self.output_text.yview_moveto(0)

    def setup_bindings(self):
        # Set initial layout via the wrapper
        theme_data = {
            "bg": "#1e1e1e",
            "fg": "white",
            "chord": "#ffcc00",
            "comment": "#64B5F6"
        }
        self.output_text.apply_layout_params(theme_data, self.font_size)
        # Right mouse key (Windows/Linux) or two-finger tap (ChromeOS)
        self.output_text.bind("<Button-3>", self.show_chord_info)

        # Mac users or touchscreens (sometimes Button-2)
        self.output_text.bind("<Button-2>", self.show_chord_info)

        # Initialize Touch Interaction
        self.setup_touch_scroll(self.input_text)
        self.setup_touch_scroll(self.output_text)

        # Bind Ctrl+A
        self.root.bind("<Control-a>", self.select_all)
        self.root.bind("<Control-A>", self.select_all)


        self.output_text.bind("<Button-1>", self.on_potential_long_press)
        self.output_text.bind("<ButtonRelease-1>", self.cancel_long_press)


    def on_potential_long_press(self, event):
        """
        Starts a timer when the user clicks.
        If held for 500ms, it triggers the chord info menu.
        """
        # Cancel any existing timer just in case
        if self.click_timer:
            self.app.root.after_cancel(self.click_timer)

        # Schedule the menu display after 500ms
        self.click_timer = self.root.after(500, lambda: self.trigger_long_press_menu(event))


    def cancel_long_press(self, event):
        """
        If the user releases the button before 500ms,
        cancel the timer so the menu doesn't pop up.
        """
        if self.click_timer:
            self.root.after_cancel(self.click_timer)
            self.click_timer = None


    def trigger_long_press_menu(self, event):
        """
        Helper to call the show_chord_info method
        manually from the timer.
        """
        self.click_timer = None
        self.show_chord_info(event)

if __name__ == "__main__":
    root = tk.Tk()
    app = ChoConverterApp(root)
    root.mainloop()
