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

class ChoConverterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ChordPro Tool - Converter & Viewer")
        self.root.geometry("1000x900")  # Slightly wider to accommodate the new toolbar

        # --- Variables & State Management ---
        self.font_size = 14
        self.is_view_mode = False
        self.is_scrolling = False
        self.column_mode = tk.StringVar(value="auto")
        self.is_fullscreen = False
        self.editor_history = ""
        self.current_editor_state = ""
        self.ui_elements = []
        self.is_performance_mode = False
        self.current_playlist = []  # List of files from the active tag
        self.current_index = -1  # Current position within the list
        self.chord_explanations = {
            # --- Slash Chords (Basnotes) ---
            "Em7/D": "Em7 with a D in the bass. Fretboard: X-5-5-4-5-X or open: 0-2-0-0-0-2",
            "C/G": "C major with a G in the bass. Fretboard: 3-3-2-0-1-0",
            "D/F#": "D major with an F# in the bass (often played with the thumb). Fretboard: 2-0-0-2-3-2",
            "G/B": "G major with a B in the bass. Fretboard: X-2-0-0-3-3",
            "Am/G": "A minor with a G in the bass. Fretboard: 3-0-2-2-1-0",

            # --- Seventh Chords ---
            "Cmaj7": "C major with a major 7th (B). Fretboard: X-3-2-0-0-0",
            "G7": "G dominant 7th. Fretboard: 3-2-0-0-0-1",
            "Am7": "A minor 7th. Fretboard: X-0-2-0-1-0",
            "Dm7": "D minor 7th. Fretboard: X-X-0-2-1-1",
            "E7": "E dominant 7th. Fretboard: 0-2-0-1-0-0",
            "B7": "B dominant 7th. Fretboard: X-2-1-2-0-2",

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
        self.settings_file = "settings.json"
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
        # Default theme name
        self.current_theme_name = "light"

        self.load_settings()

        # --- SECTION 1: TOP PANEL (Metadata & File Actions) ---
        self.top_frame = tk.Frame(root)
        self.top_frame.pack(pady=10, padx=20, fill=tk.X)
        self.ui_elements.append(self.top_frame)

        # Left Side: Artist and Song Title Input
        self.meta_frame = tk.Frame(self.top_frame)
        self.meta_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

        tk.Label(self.meta_frame, text="Artist:").grid(row=0, column=0, sticky="w")
        self.artist_entry = tk.Entry(self.meta_frame, font=("Arial", 10))
        self.artist_entry.grid(row=0, column=1, sticky="ew", padx=5)

        tk.Label(self.meta_frame, text="Title:").grid(row=1, column=0, sticky="w")
        self.title_entry = tk.Entry(self.meta_frame, font=("Arial", 10))
        self.title_entry.grid(row=1, column=1, sticky="ew", padx=5)
        self.meta_frame.columnconfigure(1, weight=1)

        # Right Side: File Operation Buttons
        self.file_btn_frame = tk.Frame(self.top_frame)
        self.file_btn_frame.pack(side=tk.RIGHT, padx=(20, 0))

        btns = [
            ("OPEN", self.open_file, "#FFD700", "black"),
            ("SAVE", self.convert_and_save, "#17499E", "white"),
            ("CLEAR", self.clear_fields, "#f44336", "white"),
            ("NEXT ⏩", self.next_song, "#4CAF50", "white")
        ]
        for txt, cmd, bg, fg in btns:
            tk.Button(self.file_btn_frame, text=txt, command=cmd, bg=bg, fg=fg, width=8).pack(side=tk.LEFT, padx=2)

        # --- SECTION 2: CENTER PANEL (ChordPro Editor) ---
        self.editor_frame = tk.Frame(root)
        self.editor_frame.pack(padx=20, fill=tk.BOTH, expand=True)
        self.ui_elements.append(self.editor_frame)

        tk.Label(self.editor_frame, text="SONG EDITOR", font=("Arial", 9, "bold")).pack(anchor="w")

        # Container for Text area + Scrollbar
        editor_container = tk.Frame(self.editor_frame)
        editor_container.pack(fill=tk.BOTH, expand=True)

        # Using standard tk.Text for better control over scrollbar width
        self.input_text = tk.Text(editor_container, wrap=tk.NONE, height=10, font=("Courier New", 11), undo=True)
        self.input_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Wide scrollbar for easier touch interaction
        self.input_scroll = tk.Scrollbar(editor_container, orient="vertical",
                                         command=self.input_text.yview, width=35)
        self.input_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.input_text.config(yscrollcommand=self.input_scroll.set)

        # --- Editor Toolbar (Directly below the text field) ---
        self.edit_tools = tk.Frame(self.editor_frame)
        self.edit_tools.pack(fill=tk.X, pady=5)

        # Transpose Controls
        tk.Label(self.edit_tools, text="  Transpose:").pack(side=tk.LEFT)
        tk.Button(self.edit_tools, text="♭", command=lambda: self.transpose_chords(-1),
                  width=3, bg="#444444", fg="white").pack(side=tk.LEFT, padx=2)
        tk.Button(self.edit_tools, text="♯", command=lambda: self.transpose_chords(1),
                  width=3, bg="#444444", fg="white").pack(side=tk.LEFT, padx=2)

        # Update Button (compact view)
        tk.Button(self.edit_tools, text="🔄 UPDATE PREVIEW", command=self.test_conversion,
                  bg="#607D8B", fg="white", font=("Arial", 9, "bold"), padx=10).pack(side=tk.LEFT)

        # Undo/Restore Button
        self.undo_btn = tk.Button(self.edit_tools, text="↩ RESTORE PREVIOUS", command=self.undo_editor,
                                  bg="#9E9E9E", fg="white", state=tk.DISABLED)
        self.undo_btn.pack(side=tk.LEFT, padx=5)

        # Small shortcut tip on the right
        tk.Label(self.edit_tools, text="Shortcut: Ctrl+S for Save / Update",
                 font=("Arial", 8, "italic"), fg="gray").pack(side=tk.RIGHT)

        # --- SECTION 3: BOTTOM PANEL (Viewer & Performance Controls) ---
        self.view_frame = tk.LabelFrame(root, text=" Viewer Settings ", padx=10, pady=5)
        self.view_frame.pack(padx=20, pady=5, fill=tk.X)

        # ROW 1: Navigation & Visual Modes
        row1 = tk.Frame(self.view_frame)
        row1.pack(fill=tk.X, pady=2)

        self.view_btn = tk.Button(row1, text="🖥 VIEW MODE", command=self.toggle_view_mode, bg="#9C27B0", fg="white",
                                  font=("Arial", 11, "bold"), height=2)
        self.view_btn.pack(side=tk.LEFT, padx=5)

        self.fs_btn = tk.Button(row1, text="📺 FULL SCREEN", command=self.toggle_fullscreen, bg="#2196F3", fg="white",
                                font=("Arial", 11), height=2)
        self.fs_btn.pack(side=tk.LEFT, padx=5)

        self.perf_btn = tk.Button(row1, text="🎭 PERF MODE", command=self.enter_performance_mode,
                                  bg="#E91E63", fg="white", font=("Arial", 10, "bold"), height=2)
        self.perf_btn.pack(side=tk.LEFT, padx=5)

        tk.Label(row1, text="  Font:").pack(side=tk.LEFT)
        tk.Button(row1, text="A+", command=lambda: self.change_font(2), width=5, height=2).pack(side=tk.LEFT, padx=2)
        tk.Button(row1, text="A-", command=lambda: self.change_font(-2), width=5, height=2).pack(side=tk.LEFT, padx=2)

        # ROW 2: Autoscroll Speed & Column Layout
        row2 = tk.Frame(self.view_frame)
        row2.pack(fill=tk.X, pady=5)

        self.scroll_btn = tk.Button(row2, text="▶ START", command=self.toggle_scroll, bg="#FF9800", width=12, height=2,
                                    font=("Arial", 10, "bold"))
        self.scroll_btn.pack(side=tk.LEFT, padx=5)

        # Speed control with large tap targets
        tk.Button(row2, text="—", font=("Arial", 14, "bold"), width=4, height=1,
                  command=lambda: self.speed_slider.set(self.speed_slider.get() - 5)).pack(side=tk.LEFT, padx=2)

        self.speed_slider = tk.Scale(row2, from_=1, to=100, orient=tk.HORIZONTAL, showvalue=False, width=25)
        self.speed_slider.set(20)
        self.speed_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        tk.Button(row2, text="+", font=("Arial", 14, "bold"), width=4, height=1,
                  command=lambda: self.speed_slider.set(self.speed_slider.get() + 5)).pack(side=tk.LEFT, padx=2)

        # --- KEYBOARD SHORTCUTS ---
        # Control + '+' or '=' for Zoom In
        self.root.bind("<Control-plus>", lambda e: self.change_font(2))
        self.root.bind("<Control-equal>", lambda e: self.change_font(2))  # Common since '+' usually shares key with '='

        # Control + '-' for Zoom Out
        self.root.bind("<Control-minus>", lambda e: self.change_font(-2))

        self.theme_btn = tk.Button(row1, text="🌓 LIGHT", command=self.toggle_theme, width=16, height=2)
        self.theme_btn.pack(side=tk.LEFT, padx=5)

        # Layout toggles at the end of Row 2
        tk.Label(row2, text="  Layout:").pack(side=tk.LEFT, padx=(10, 0))
        for text, mode in [("1", "one"), ("2", "two"), ("Auto", "auto")]:
            tk.Radiobutton(row2, text=text, variable=self.column_mode, value=mode,
                           command=self.render_view, indicatoron=0, width=5, height=2).pack(side=tk.LEFT, padx=1)

        # --- THE VIEWER (Main Output Area) ---
        self.viewer_main_frame = tk.Frame(root)
        self.viewer_main_frame.pack(padx=20, pady=(0, 10), fill=tk.BOTH, expand=True)
        self.ui_elements.append(self.viewer_main_frame)

        # Output text widget
        self.output_text = tk.Text(self.viewer_main_frame, wrap=tk.NONE,
                                   font=("Arial", self.font_size, "bold"),
                                   bg="#1e1e1e", fg="#ffffff")
        self.output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Wide scrollbar positioned directly next to the viewer
        self.output_scroll = tk.Scrollbar(self.viewer_main_frame, orient="vertical",
                                          command=self.output_text.yview, width=40)
        self.output_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.output_text.config(yscrollcommand=self.output_scroll.set)

        # Monospaced font configuration for alignment
        self.output_text.configure(font=("DejaVu Sans Mono", 11))

        # Syntax Highlighting Tags
        self.output_text.tag_configure("chord", foreground="#ffcc00")
        self.output_text.tag_configure("comment", foreground="#64B5F6", font=("Arial", self.font_size, "italic"))

        # Right mouse key (Windows/Linux) or two-finger tap (ChromeOS)
        self.output_text.bind("<Button-3>", self.show_chord_info)

        # Mac users or touchscreens (sometimes Button-2)
        self.output_text.bind("<Button-2>", self.show_chord_info)

        # Initialize Touch Interaction
        self.setup_touch_scroll(self.input_text)
        self.setup_touch_scroll(self.output_text)
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
        text = self.input_text.get("1.0", tk.END)

        # The chromatic scale (sharps)
        notes_sharp = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        # Mapping for flats to sharps for calculation purposes
        map_to_sharp = {'Db': 'C#', 'Eb': 'D#', 'Gb': 'F#', 'Ab': 'G#', 'Bb': 'A#', 'Cb': 'B', 'Fb': 'E'}

        # Regex:
        # ([A-G][#b]?) captures the root note including existing # or b
        # (m|maj|min|dim|aug|sus|add|alt|[\d/]*) captures the rest (suffix)
        chord_pattern = r'([A-G][#b]?)(m|maj|min|dim|aug|sus|add|alt|[\d/]*)'

        def replace_chord(match):
            full_root = match.group(1)  # e.g., "A#" or "Bb"
            suffix = match.group(2)  # e.g., "m7"

            # 1. Normalize the root note to a sharp from our list
            root = map_to_sharp.get(full_root, full_root)

            if root in notes_sharp:
                current_idx = notes_sharp.index(root)
                # 2. Calculate the new index (modulo 12 ensures wrapping from B to C)
                new_idx = (current_idx + delta) % 12
                new_root = notes_sharp[new_idx]

                # 3. Return the new root + the original suffix
                return new_root + suffix

            return match.group(0)

        # Use a function in re.sub to process each found chord
        new_text = re.sub(chord_pattern, replace_chord, text)

        # Update the editor and viewer
        self.input_text.delete("1.0", tk.END)
        self.input_text.insert(tk.END, new_text)
        self.test_conversion()

    def draw_chord_diagram(self, chord_name, fret_string):
        """
        Creates a popup window with a visual guitar chord diagram.
        Expects fret_string format: 'X-3-2-0-1-0'
        """
        # Create popup window
        top = tk.Toplevel(self.root)
        top.title(f"Diagram: {chord_name}")
        top.geometry("250x320")
        top.configure(bg="#2C2C2C")

        # Clean the input (remove 'Fretboard:' prefix if present)
        clean_frets = fret_string.replace("Fretboard:", "").strip().split('-')

        # Canvas settings
        c = tk.Canvas(top, width=200, height=250, bg="#2C2C2C", highlightthickness=0)
        c.pack(pady=20)

        # Grid constants
        margin_x, margin_y = 40, 40
        string_spacing = 25
        fret_spacing = 35

        # Draw Frets (5 frets)
        for i in range(6):
            y = margin_y + (i * fret_spacing)
            line_width = 4 if i == 0 else 1  # Thicker line for the nut
            c.create_line(margin_x, y, margin_x + 125, y, fill="white", width=line_width)

        # Draw Strings (6 strings)
        for i in range(6):
            x = margin_x + (i * string_spacing)
            c.create_line(x, margin_y, x, margin_y + 175, fill="#AAAAAA")

        # Draw Fingers/Markers
        for i, fret in enumerate(clean_frets):
            x = margin_x + (i * string_spacing)

            if fret.upper() == 'X':
                # Draw an X for muted strings
                c.create_text(x, margin_y - 15, text="X", fill="#FF5555", font=("Arial", 10, "bold"))
            elif fret == '0':
                # Draw an O for open strings
                c.create_oval(x - 5, margin_y - 20, x + 5, margin_y - 10, outline="#55FF55", width=2)
            else:
                # Draw a solid circle for pressed frets
                f_num = int(fret)
                y = margin_y + (f_num * fret_spacing) - (fret_spacing / 2)
                c.create_oval(x - 8, y - 8, x + 8, y + 8, fill="#2196F3", outline="white")

        # Add chord name label
        tk.Label(top, text=chord_name, fg="white", bg="#2C2C2C", font=("Arial", 14, "bold")).pack()

    def show_chord_info(self, event):
        """Displays a context menu with chord explanations when triggered."""
        # Find the index under the mouse cursor
        idx = self.output_text.index(f"@{event.x},{event.y}")

        # Custom logic to find the full chord name (including slashes, sharps, and flats)
        line_start = self.output_text.index(f"{idx} linestart")
        line_end = self.output_text.index(f"{idx} lineend")
        line_text = self.output_text.get(line_start, line_end)

        # Calculate the character offset within that line
        char_offset = int(idx.split('.')[1])

        # Updated pattern to include '#' and 'b' throughout the chord name
        pattern = r'[A-G][#b]?[a-zA-Z0-9/#b]*'
        matches = re.finditer(pattern, line_text)

        word = ""
        for match in matches:
            if match.start() <= char_offset <= match.end():
                word = match.group()
                # Clean up trailing punctuation if the regex caught any
                word = word.rstrip('./')
                break

        # Check if an explanation exists for this chord
        explanation = self.chord_explanations.get(word)

        if explanation:
            info_menu = tk.Menu(self.root, tearoff=0)
            info_menu.add_command(label=f"CHORD: {word}", state=tk.DISABLED)
            info_menu.add_separator()

            parts = explanation.split("Fretboard:")
            info_menu.add_command(label=parts[0].strip(), command=lambda: None)

            if len(parts) > 1:
                fret_val = parts[1].strip()
                info_menu.add_command(
                    label=f"Fingering: {fret_val}",
                    command=lambda: self.draw_chord_diagram(word, fret_val)
                )

            info_menu.post(event.x_root, event.y_root)

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

        # File processing logic
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Extract metadata using regex
        title_match = re.search(r'\{(?:title|t):\s*(.*)\}', content, re.IGNORECASE)
        artist_match = re.search(r'\{(?:artist|a):\s*(.*)\}', content, re.IGNORECASE)

        self.title_entry.delete(0, tk.END)
        if title_match: self.title_entry.insert(0, title_match.group(1).strip())

        self.artist_entry.delete(0, tk.END)
        if artist_match: self.artist_entry.insert(0, artist_match.group(1).strip())

        # Update text areas
        plain_text = self.chordpro_to_plain(content)
        self.input_text.delete("1.0", tk.END)
        self.input_text.insert(tk.END, plain_text)

        self.output_text.delete("1.0", tk.END)
        self.output_text.insert(tk.END, content)
        self.current_editor_state = plain_text
        self.render_view()

    def load_settings(self):
        """Loads user preferences (theme, last category, sorting) from JSON."""
        self.settings_file = "settings.json"
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    # Load theme, category and sorting with fallback defaults
                    self.current_theme_name = settings.get("theme", "light")
                    self.active_tag = settings.get("last_category", "All")
                    self.sort_song_by = settings.get("last_sort", "none")
            except:
                self._set_defaults()
        else:
            self._set_defaults()

    def toggle_theme(self):
        """Cycles through the themes based on the dictionary keys."""
        # Create a list of all theme names
        theme_names = list(self.themes.keys())

        # Find the index of the current theme
        try:
            current_index = theme_names.index(self.current_theme_name)
        except ValueError:
            current_index = 0

        # Calculate the next index (looping back to 0 at the end)
        next_index = (current_index + 1) % len(theme_names)
        self.current_theme_name = theme_names[next_index]

        # Apply, save and render
        self._apply_theme()
        self.save_settings()
        self.render_view(self.current_editor_state)

    def _apply_theme(self):
        """
        Applies the selected theme with hierarchical coloring (layering).
        Uses 'surface' colors for containers to create visual depth.
        """
        theme = self.themes[self.current_theme_name]
        self.root.config(bg=theme["app_bg"])

        action_colors = [
            "#ffd700", "#17499e", "#f44336", "#4caf50",
            "#444444", "#607d8b", "#9e9e9e",
            "#9c27b0", "#2196f3", "#e91e63", "#ff9800"
        ]

        def apply_to_widget(widget, is_inside_container=False):
            w_type = widget.winfo_class()

            # Determine background based on whether it's a top-level frame or a sub-frame
            bg_color = theme["surface"] if is_inside_container else theme["app_bg"]

            # --- Frames and Containers ---
            if w_type in ("Frame", "LabelFrame"):
                # If it's a LabelFrame (like Viewer Settings), use the 'surface' color
                current_surface = theme["surface"] if w_type == "LabelFrame" else bg_color
                widget.config(bg=current_surface)
                if w_type == "LabelFrame":
                    widget.config(fg=theme["label_fg"], font=("Arial", 10, "bold"))

                # Pass down the state that we are now inside a themed container
                for child in widget.winfo_children():
                    apply_to_widget(child, is_inside_container=(w_type == "LabelFrame"))

            # --- Labels ---
            elif w_type == "Label":
                # Labels use the accent color (label_fg) and the parent's background
                widget.config(bg=widget.master.cget("bg"), fg=theme["label_fg"])

            # --- Text and Entry Fields ---
            elif w_type in ("Entry", "Text"):
                if widget == self.output_text:
                    widget.config(bg=theme["bg"], fg=theme["fg"], insertbackground=theme["fg"])
                else:
                    widget.config(bg=theme["input_bg"], fg=theme["input_fg"],
                                  insertbackground=theme["input_fg"], relief=tk.FLAT)

            # --- Buttons and Radiobuttons ---
            elif w_type in ("Button", "Radiobutton"):
                try:
                    current_bg = str(widget.cget("bg")).lower()
                except:
                    current_bg = ""

                if current_bg not in action_colors:
                    if w_type == "Radiobutton":
                        widget.config(
                            bg=widget.master.cget("bg"),
                            fg=theme["label_fg"],
                            selectcolor=theme["input_bg"],
                            activebackground=theme["surface"]
                        )
                    else:
                        widget.config(bg=theme["btn_bg"], fg=theme["btn_fg"], relief=tk.RAISED)

            # --- Scale ---
            elif w_type == "Scale":
                widget.config(
                    bg=widget.master.cget("bg"),
                    fg=theme["label_fg"],
                    troughcolor=theme["input_bg"],
                    highlightthickness=0
                )

            # If it wasn't a frame (which handles its own children above),
            # iterate through children normally
            if w_type not in ("Frame", "LabelFrame"):
                for child in widget.winfo_children():
                    apply_to_widget(child, is_inside_container)

        # Start the process from root - it will now include frames correctly
        apply_to_widget(self.root)
        # workaround: apply theme also to frame
        self.view_frame.config(fg=theme["label_fg"], bg=theme["app_bg"])

        # 2. Update PGN/Chord Syntax Highlighting (CRITICAL PART)
        # We reset the tags to the current theme's colors
        for t in ["chord", "comment", "normal", "alt_move"]:
            self.output_text.tag_delete(t)

        # Configure tags with colors from the active theme
        self.output_text.tag_config("normal", foreground=theme["fg"])
        self.output_text.tag_config("chord", foreground=theme["chord"])
        self.output_text.tag_config("comment", foreground=theme["comment"], font=("Arial", self.font_size, "italic"))
        self.output_text.tag_config("alt_move", foreground=theme["alt"])

        # Set priority (z-order) of the tags
        self.output_text.tag_raise("chord")
        self.output_text.tag_raise("comment")
        self.output_text.tag_lower("normal")

        # 4. Update the Theme Cycle Button text and style
        theme_names = list(self.themes.keys())
        next_idx = (theme_names.index(self.current_theme_name) + 1) % len(theme_names)
        current_name = self.current_theme_name.replace("_", " ").upper()
        next_name = theme_names[next_idx].replace("_", " ").upper()

        self.theme_btn.config(
            text=f"🎨 {current_name} ➔ {next_name}",
            bg=theme["btn_bg"],
            fg=theme["btn_fg"]
        )

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

    def change_font(self, delta):
        """Adjusts font size and triggers a re-render to update layout calculations."""
        self.font_size += delta
        # Apply updated font to tags
        self.output_text.configure(font=("Courier New", self.font_size, "bold"))
        self.output_text.tag_configure("comment", font=("Arial", self.font_size, "italic"))

        # Re-render view to recalculate column distributions with new size
        res = self.generate_cho_content()
        self.render_view(content=res)

    def toggle_view_mode(self):
        """Switches the UI between Editor (Edit) and Presenter (View) modes."""
        if not self.is_view_mode:
            # --- SWITCH TO VIEW MODE ---
            # Hide all main UI elements to clear the screen
            for el in self.ui_elements:
                el.pack_forget()

            # Ensure the viewer frames are visible
            self.view_frame.pack(padx=20, pady=5, fill=tk.X)
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
            self.view_frame.pack_forget()

            # Restore editor components to the layout
            self.top_frame.pack(pady=10, padx=20, fill=tk.X)
            self.editor_frame.pack(padx=20, fill=tk.BOTH, expand=True)

            # Re-add controls and viewer at the bottom of the editor
            self.view_frame.pack(padx=20, pady=5, fill=tk.X)
            self.viewer_main_frame.pack(padx=20, pady=(0, 10), fill=tk.BOTH, expand=True)

            self.view_btn.config(text="🖥 VIEW MODE", bg="#9C27B0")
            self.is_view_mode = False

    def enter_performance_mode(self):
        """Optimizes the screen for live performance by removing all distractions."""
        print("enter_performance_mode")
        self.is_performance_mode = True

        # 1. Hide Editor and Top navigation bars
        self.top_frame.pack_forget()
        self.editor_frame.pack_forget()
        self.view_frame.pack_forget()  # Hide the button bar (A+, START, etc.)

        # 2. Activate Fullscreen mode
        self.root.attributes("-fullscreen", True)

        # 3. Scale the viewer to fill the entire screen
        # Remove margins for a truly 'clean' visual presentation
        self.viewer_main_frame.pack_configure(padx=0, pady=0)

        # 4. Create floating overlay buttons for navigation/exit
        self.exit_perf_btn = tk.Button(self.root, text="✕ EXIT", command=self.exit_performance_mode,
                                       bg="#333333", fg="#888888", font=("Arial", 9),
                                       relief=tk.FLAT, padx=15, pady=10)
        self.exit_perf_btn.place(relx=1.0, rely=0.0, anchor="ne")

        self.perf_menu_btn = tk.Button(self.root, text="MENU ☰", command=self.toggle_perf_menu,
                                       bg="#2196F3", fg="white", font=("Arial", 12, "bold"),
                                       relief=tk.RAISED, padx=20, pady=15)
        self.perf_menu_btn.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)

        # Bind hardware keys for quick access
        self.root.bind("<Escape>", lambda e: self.exit_performance_mode())
        self.root.bind("<Right>", lambda e: self.next_song())

    def toggle_perf_menu(self):
        """Safely shows or hides the floating performance menu."""
        # First check if the attribute exists AND if the widget hasn't been destroyed
        if hasattr(self, 'perf_menu_frame') and self.perf_menu_frame.winfo_exists():
            if self.perf_menu_frame.winfo_viewable():
                self.hide_perf_menu()
                return
        else:
            # If it doesn't exist (e.g. after destroy), recreate the frame
            self.perf_menu_frame = tk.Frame(self.root, bg="#424242", padx=10, pady=10,
                                            highlightbackground="white", highlightthickness=1)

        # Clear existing menu items and rebuild
        for widget in self.perf_menu_frame.winfo_children():
            widget.destroy()

        # --- Performance Menu Options ---
        options = [
            ("⏩ NEXT", self.perf_action_next, "#4CAF50"),
            ("▶ START SCROLL", self.perf_action_scroll, "#FF9800"),
            ("A+", lambda: self.perf_action_font(2), "#607D8B"),
            ("A-", lambda: self.perf_action_font(-2), "#607D8B"),
            ("1 / 2 COLUMNS", self.perf_action_layout, "#9C27B0")
        ]

        for text, cmd, color in options:
            tk.Button(self.perf_menu_frame, text=text, command=cmd,
                      bg=color, fg="white", font=("Arial", 11, "bold"),
                      width=15, height=2, pady=5).pack(pady=2)

        # Position the menu above the Menu button
        self.perf_menu_frame.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-85)

    def perf_action_next(self):
        """Closes menu and triggers next song."""
        self.perf_menu_frame.place_forget()
        self.next_song()

    def perf_action_scroll(self):
        """Closes menu and toggles autoscroll."""
        self.perf_menu_frame.place_forget()
        self.toggle_scroll()

    def perf_action_font(self, delta):
        """Adjusts font size and starts a timer to auto-hide the menu."""
        self.change_font(delta)

        # Cancel previous timer if the user is still interacting
        if hasattr(self, '_menu_timer_id'):
            self.root.after_cancel(self._menu_timer_id)

        # Auto-hide the menu after 3 seconds of inactivity
        self._menu_timer_id = self.root.after(3000, self.hide_perf_menu)

    def hide_perf_menu(self):
        """Safely hides the performance menu."""
        if hasattr(self, 'perf_menu_frame'):
            self.perf_menu_frame.place_forget()

    def perf_action_layout(self):
        """Toggles between single and dual column layout in performance mode."""
        self.perf_menu_frame.place_forget()
        current = self.column_mode.get()
        self.column_mode.set("two" if current == "one" else "one")
        self.render_view()

    def exit_performance_mode(self):
        """Restores the UI to standard View/Edit mode."""
        self.is_performance_mode = False
        self.root.attributes("-fullscreen", False)

        # 1. Clean up floating performance elements
        if hasattr(self, 'exit_perf_btn'): self.exit_perf_btn.destroy()
        if hasattr(self, 'perf_menu_btn'): self.perf_menu_btn.destroy()
        if hasattr(self, 'perf_menu_frame'): self.perf_menu_frame.destroy()

        # 2. Restore standard scrollbar
        self.output_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 3. Restore container margins
        self.viewer_main_frame.pack_configure(padx=20, pady=(0, 10))

        # 4. Trigger normal UI restoration
        self.is_view_mode = True
        self.toggle_view_mode()

        # Update the Fullscreen button state in the main UI
        if hasattr(self, 'fs_btn'):
            self.fs_btn.config(text="📺 FULL SCREEN", bg="#2196F3")
            self.is_fullscreen = False

    def chordpro_to_plain(self, chordpro_text):
        """Translates ChordPro format back to a plain text editor view (Chords above lyrics)."""
        lines = chordpro_text.splitlines()
        output = []

        for line in lines:
            # Skip metadata tags (handled by entry fields)
            if line.startswith('{title:') or line.startswith('{artist:') or not line.strip():
                if not line.strip(): output.append("")
                continue

            # Convert section tags (like chorus) to readable headers
            comment_match = re.search(r'\{(.*?)\}', line)
            if comment_match:
                content = comment_match.group(1).strip()
                if "start_of_chorus" in content.lower():
                    output.append("[Chorus]")
                elif "end_of_chorus" in content.lower():
                    pass  # Closing tag not needed in plain text view
                else:
                    clean = re.sub(r'^(comment|c):\s*', '', content, flags=re.IGNORECASE)
                    output.append(f"[{clean}]")
                continue

            # Process chords embedded in brackets
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

                # Use a marker '.' to identify chord lines internally
                output.append("." + "".join(chord_line).rstrip())
                output.append("".join(text_line))
            else:
                output.append(line)

        return "\n".join(output)

    def render_view(self, content=None):
        """Converts internal data to formatted view with column layouts."""
        self.root.update_idletasks()

        if content:
            self.last_chordpro_data = content
        elif hasattr(self, 'last_chordpro_data'):
            content = self.last_chordpro_data
        else:
            content = self.output_text.get("1.0", "end-1c")

        self.output_text.delete("1.0", tk.END)

        # DO NOT re-configure tags here. 
        # Just make sure the hierarchy is correct before inserting text.

        # Parse ChordPro into a list of (text, tag) tuples for rendering
        chordpro_content = content.splitlines()
        rendered_lines = []
        for line in chordpro_content:
            if line.startswith('.'):
                # Remove internal marker and treat as chord line
                rendered_lines.append((line[1:], "chord"))
                continue

            if line.startswith('{title:') or line.startswith('{artist:'):
                continue

            comment_match = re.search(r'\{(.*?)\}', line)
            if comment_match:
                c_content = comment_match.group(1).strip()
                if "chorus" in c_content.lower():
                    clean_line = "--- CHORUS ---" if "start" in c_content.lower() else "--------------"
                else:
                    # Clean the tag identifier to show only the text inside brackets
                    clean_val = re.sub(r'^(comment|c|title|artist|t|a):\s*', '', c_content, flags=re.IGNORECASE)
                    clean_line = f"({clean_val})"
                rendered_lines.append((clean_line, "comment"))
                continue

            # Detect embedded chords (e.g., Hey[D] Jude) and split into chord/lyric lines
            if '[' in line and ']' in line:
                chord_line = [" "] * 150
                clean_text = []
                current_pos = 0

                # Split by brackets to separate chords from text
                parts = re.split(r'(\[.*?\])', line)

                for part in parts:
                    if part.startswith('[') and part.endswith(']'):
                        # It is a chord: extract text and place at current character position
                        chord_text = part[1:-1]
                        for j, char in enumerate(chord_text):
                            if current_pos + j < len(chord_line):
                                chord_line[current_pos + j] = char
                    else:
                        # It is normal text: update position for next chord alignment
                        clean_text.append(part)
                        current_pos += len(part)

                rendered_lines.append(("".join(chord_line).rstrip(), "chord"))
                rendered_lines.append(("".join(clean_text), None))
            else:
                rendered_lines.append((line, None))

        # Column calculation logic
        pixel_width = self.output_text.winfo_width()
        mid_point = pixel_width // 2
        self.output_text.configure(tabs=(mid_point, tk.LEFT))

        char_width = self.font_size * 0.65
        total_chars_avail = pixel_width // char_width
        max_line_len = max([len(l[0]) for l in rendered_lines]) if rendered_lines else 0

        # Decide if columns are needed based on mode and line length
        mode = self.column_mode.get()
        use_two_columns = False

        if mode == "one":
            use_two_columns = False
        elif mode == "two":
            use_two_columns = True
        else:  # auto mode: use 2 columns if max length fits well within half screen
            use_two_columns = max_line_len > 0 and max_line_len < (total_chars_avail * 0.45)

        if use_two_columns:
            mid = (len(rendered_lines) + 1) // 2
            left_side = rendered_lines[:mid]
            right_side = rendered_lines[mid:]

            for i in range(len(left_side)):
                # Gebruik "normal" als de tag None is
                l_tag = left_side[i][1] if left_side[i][1] else "normal"
                self.output_text.insert(tk.END, left_side[i][0], l_tag)

                if i < len(right_side):
                    r_tag = right_side[i][1] if right_side[i][1] else "normal"
                    self.output_text.insert(tk.END, "\t", "normal")  # Tab is altijd normal
                    self.output_text.insert(tk.END, right_side[i][0], r_tag)
                self.output_text.insert(tk.END, "\n", "normal")
        else:
            for text, tag in rendered_lines:
                # Gebruik "normal" als de tag None is
                final_tag = tag if tag else "normal"
                self.output_text.insert(tk.END, text + "\n", final_tag)

    def is_chord_line(self, line):
        """Heuristic check to see if a line consists primarily of music chords."""
        # Remove common delimiters to isolate the text
        clean = re.sub(r'[|*:\;!?\[\]\(\)]', ' ', line).strip()
        if not clean: return False

        words = clean.split()
        # Pattern allows standard music notation, slash chords, and complex extensions
        pattern = r'^[A-G][b#]?(?:maj|min|m|M|dim|aug|sus|add|alt|dim|[\d/])*$'

        chords = [w for w in words if re.match(pattern, w, re.IGNORECASE)]

        # If > 60% of words look like chords, treat the line as a chord line
        return len(chords) > 0 and len(chords) >= len(words) * 0.6

    def generate_cho_content(self):
        """Converts editor text back into ChordPro format with embedded brackets."""
        artist, title = self.artist_entry.get().strip(), self.title_entry.get().strip()

        lines = self.input_text.get("1.0", tk.END).splitlines()
        cho = [f"{{title: {title}}}", f"{{artist: {artist}}}", ""]
        i, in_chorus = 0, False

        while i < len(lines):
            line = lines[i]

            # 1. Section detection (e.g., [Chorus])
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

            # 2. Check for chord lines and merge them into the lyric line below
            is_marker_line = line.startswith('.')
            current_line_clean = line[1:] if is_marker_line else line

            if (is_marker_line or self.is_chord_line(line)) and (i + 1 < len(lines)) and not self.is_chord_line(
                    lines[i + 1]):
                # Identify positions of chords in the current line
                chords = [(m.start(), m.group()) for m in re.finditer(r'\S+', current_line_clean)]

                # Next line is the target lyric line
                next_line = lines[i + 1]
                next_line_clean = next_line[1:] if next_line.startswith('.') else next_line
                txt = list(next_line_clean)

                # Insert chords from right to left to maintain index accuracy
                for pos, c in reversed(chords):
                    fmt = f"[{c.strip('()[]{}')}]"
                    if pos < len(txt):
                        txt.insert(pos, fmt)
                    else:
                        # Extend line with spaces if chord is further right than text
                        txt.append(' ' * (pos - len(txt)) + fmt)

                cho.append("".join(txt))
                i += 2
            else:
                # 3. Handle standalone text or individual chord lines
                if line.strip():
                    if is_marker_line or self.is_chord_line(line):
                        # Wrap standalone chords in brackets
                        cho.append(re.sub(r'(\S+)', lambda m: f"[{m.group().strip('()[]{}')}]", current_line_clean))
                    else:
                        cho.append(current_line_clean)
                else:
                    # Close chorus on empty lines
                    if in_chorus:
                        cho.append("{end_of_chorus}")
                        in_chorus = False
                    cho.append("")
                i += 1

        # Final cleanup for chorus tags
        if in_chorus:
            cho.append("{end_of_chorus}")

        return "\n".join(cho)

    def convert_and_save(self):
        """Generates the .cho file and saves it to disk."""
        artist, title = self.artist_entry.get().strip(), self.title_entry.get().strip()
        if not artist or not title:
            messagebox.showwarning("Error", "Please fill in Artist and Title before saving.")
            return

        res = self.generate_cho_content()

        # Save to file using standardized naming convention
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
        widget.tag_add("sel", "1.0", "end")
        return "break"

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
        res = self.generate_cho_content()
        self.render_view(content=res)
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
            res = self.generate_cho_content()
            self.render_view(content=res)

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
            self.view_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)
            self.view_frame.tkraise()

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
        if self.is_scrolling:
            self.is_scrolling = False
            self.scroll_btn.config(text="▶ START", bg="#FF9800")
            if hasattr(self, '_scroll_job'):
                self.root.after_cancel(self._scroll_job)
        else:
            self.is_scrolling = True
            self.start_countdown(10)  # Start 10-second lead-in

    def start_countdown(self, seconds):
        """Displays a countdown timer on the UI button before scrolling begins."""
        if not self.is_scrolling: return

        if seconds > 0:
            self.scroll_btn.config(text=f"⏳ WAIT {seconds}", bg="#5bc0de")
            self.root.after(1000, lambda: self.start_countdown(seconds - 1))
        else:
            self.scroll_btn.config(text="■ STOP", bg="#f44336")
            self.run_scroll()

    def run_scroll(self):
        """Executes the pixel-by-pixel scroll movement based on slider speed."""
        if self.is_scrolling:
            self.output_text.yview_scroll(1, "pixels")
            # Calculate dynamic delay: higher slider value = lower delay
            delay = max(1, int(210 - (self.speed_slider.get() * 5)))
            self._scroll_job = self.root.after(delay, self.run_scroll)

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
        new_content = self.generate_cho_content()

        # 3. Update the presenter view
        self.render_view(content=new_content)

        # 4. Force graphical update - Essential for Chromebooks while in fullscreen
        self.root.update_idletasks()

        # Reset scroll position to top
        self.output_text.yview_moveto(0)

if __name__ == "__main__":
    root = tk.Tk()
    app = ChoConverterApp(root)
    root.mainloop()
