# 🎵 ChordPro & Songbook Manager Pro

A powerful, touch-optimized Python application for musicians to manage ChordPro files, organize setlists, and generate professional-grade songbooks.

## 🚀 Features

-   **Touch-Friendly Interface:** Fullscreen UI with oversized buttons and extra-wide scrollbars, specifically designed for live performance on touchscreens.
-   **ChordPro Editor:** Advanced editor featuring syntax highlighting for chords, text, and annotations.
-   **Chord Recognition:** Click on complex chords (e.g., `Em7/D` or `D/F#`) to instantly view explanations and fingering diagrams.
-   **Songbook PDF Generator:**
    -   **Smart Layout:** Automatically calculates single or double-column layouts to maximize page usage.
    -   **Professional Index:** Features a Table of Contents with sequence numbers and dynamic page numbering.
    -   **Typography Rules:** Prevents "orphans" by ensuring a minimum of 5 lines per page, keeping verses together.
    -   **File Tracking:** Includes the filename in the footer for easy document management.
-   **OSSB Export:** Export complete setlists to the OpenChord format (`.ossb`), including all `.ost` song files and a synchronized `.osts` index/set file.
-   **Setlist Management:** Create categories (tags) and drag-and-drop songs to define the perfect performance order.

## 📝 Syntax & Formatting

The application supports the standard ChordPro structure with specific enhancements:

### Basic Structure
-   **Chords:** Place chords within the text using square brackets: `[G]Lately, [C]I've been...`
-   **Metadata:** Use `{t: Title}` for the song title and `{a: Artist}` for the artist name.
-   **Chord-only Lines:** Lines starting with a period (`.`) are treated as dedicated chord rows for precise alignment.

### PGN / Technical Notation
The editor utilizes specific patterns for additional context:
-   **Alternative Moves/Notes:** Enclosed in parentheses `( )`.
-   **Comments:** Displayed within curly brackets `{ }`.
-   **Fingerings:** Uses the syntax `Fretboard: X-0-2-2-1-0` within the internal database to render visual guitar diagrams.

## 🛠 Installation

1.  Ensure Python 3.10 or higher is installed.
2.  Install the required libraries:
    ```bash
    pip install tkinter weasyprint
    ```
    *Note: WeasyPrint may require additional system dependencies such as Pango or Cairo depending on your Operating System.*

3.  Launch the application:
    ```bash
    python main.py
    ```

## 📂 File Structure

-   `*.cho`: Your song library in ChordPro format.
-   `tags.json`: Stores all categories and the manual setlist ordering.
-   `SongbookPDFGenerator.py`: The engine responsible for PDF rendering.

## 📄 PDF Export Logic

The generator automatically selects the optimal layout based on song length:
-   **Short Songs:** Single column, large font (10pt).
-   **Medium Songs:** Two columns (8.5pt or 10pt) to keep the song on a single A4 sheet.
-   **Long Songs:** Automatic multi-page transition, maintaining at least 5 lines on the final page to prevent awkward breaks.

---
*Developed with passion for live music performances.*