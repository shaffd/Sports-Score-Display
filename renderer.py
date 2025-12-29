from PIL import Image, ImageDraw, ImageFont, ImageTk
import time
import tkinter as tk
from display_utils import get_results
from data_fetcher import DataFetcher

# Display constants
WIDTH, HEIGHT = 64, 32
DISPLAY_TIME = 5   # Seconds per card (using low number just to test)

# Load a basic font
# Can be swapped for any .ttf file later for any custom fonts
FONT = ImageFont.load_default()
FONT_SMALL = ImageFont.truetype("arial.ttf", 8)

def get_text_size(draw, text, font):
    """Helper function to get text width/height.  Will work with all pillow versions 9.x and 10.x"""
    try:
        # For Pillow 10.0 or later
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
    except AttributeError:
        # For Pillow 9.x fallback
        w, h = draw.textsize(text, font=font)
    return w, h

def center_text(draw, text, y, font=FONT):
    """Helper function to center the text horizontally on the 64x32 display"""
    w, h = get_text_size(draw, text, font)
    x = (WIDTH - w) // 2
    draw.text((x, y), text, font = font, fill = "white")    # can replace "white" with (255,255,255)

def draw_game_image(card: dict) -> Image.Image:
    """
    Render a card dict into a PIL Image sized WIDTH x HEIGHT
    Card types:
        - header: {type: "header", sport: "MLB"}
        - message: {type: "message", title: "..."}
        - game: fields like home_logo/away_logo...
    """
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    draw = ImageDraw.Draw(img)

    ctype = card.get("type", "game")
    
    if ctype == "header":
        # Big, centered sport title
        title = card.get("title", card.get("sport", ""))
        center_text(draw, title.upper(), y=(HEIGHT // 2) - 4)

    elif ctype == "message":
        "Center the message text"
        center_text(draw, card.get("title", "Message"), y=(HEIGHT // 2) - 4)

    else:
        # Game card
        # Read the standardized keys from display_utils.py
        home_logo = card.get("home_logo") #or card.get("home_team") or ""
        away_logo = card.get("away_logo") #or card.get("away_team") or ""
        home_score = card.get("home_score", "")
        away_score = card.get("away_score", "")
        status = card.get("status_text", "")
        marker = card.get("marker")
        
        # center_text(draw, status, y=2)
        # Status line handling
        status = card.get("status_text", "")
        if status:
            # Split into two lines if status starts with "In Progress"
            if status.startswith("In Progress"):
                parts = status.split(":", 1)
                line1 = "In Progress"
                line2 = parts[1].strip() if len(parts) > 1 else ""
                # Draw the first line higher
                center_text(draw, line1, y = 2) # can add font=FONT_SMALL after y=2 - uses small font defined above
                # Second line just below
                center_text(draw, line2, y = 10) # can add font=FONT_SMALL after y=10 - uses small font defined above
            else:
                # Shorter statuses like "Final" or "Scheduled"
                center_text(draw, status, y = 2)

        # Compose main score line: left half shows away info, right half shows home info
        # We'll show: [2/3 LOGO][space][marker if any][space][away_score]   -   [home_score][space][marker][space][2/3 LOGO]
        # For the mock renderer we will show logos as text near edges (since we don't have graphics here)

        ### Next block is JUST to grab text instead of full URL for logo for laptop display only
        ### Will need to redo this whole rendering section for the actual 32x64 display
        # away_text = away_logo.split("/")[-1][:3].upper() if away_logo.startswith("http") else str(away_logo)
        # home_text = home_logo.split("/")[-1][:3].upper() if home_logo.startswith("http") else str(home_logo)
        away_text = card.get("away_team", card.get("away_logo", ""))[:3]
        home_text = card.get("home_team", card.get("home_logo", ""))[:3]

        # Left portion (away): place away_logo text near left edge (partially off-screen look simulated)
        # Draw away logo text at x ~ -10 to simulate "2/3 on screen" (clipped naturally)
        try:
            # Try to center with approximate positions
            # Left logo (partially off-screen)
            draw.text((-4, 8), away_text, font=FONT, fill = (180,180,180))
        except Exception:
            draw.text((0, 8), away_text, font=FONT, fill=(180,180,180))

        # Right portion (home): draw right-aligned, partially off-screen on the right
        w_home, _ = get_text_size(draw, home_text, FONT)
        draw.text((WIDTH - w_home + 4, 8), home_text, font=FONT, fill=(180,180,180))

        # Draw the score pair centered horizontally with a dash in the absolute center
        score_text = f"{away_score}  -  {home_score}"
        center_text(draw, score_text, y=12)

        # Marker dot for possession / at bat (none for hockey)
        if marker in ("away", "home"):
            # Compute approx positions of left / right score numbers
            # Measure width of left part up to the dash
            left_part = f"{away_score}  -"
            w_left, _ = get_text_size(draw, left_part, font=FONT)
            # Xof left number start relative to centered text:
            total_w, _ = get_text_size(draw, score_text, font=FONT)
            center_x = (WIDTH - total_w) // 2
            if marker == "away":
                dot_x = center_x + max(0, w_left - 8)
                dot_y = 14
            else:
                # Home marker near right number: estimate position near end of string
                dot_x = center_x + total_w -6
                dot_y = 14
            # Draw a small square dot
            draw.rectangle([dot_x, dot_y, dot_x+2, dot_y+2], fill=(255,255,255))

    return img

# --- Tkinter single-window display manager ---
class DisplayWindow:
    def __init__(self, results, delay_seconds=DISPLAY_TIME):
        self.root = tk.Tk()
        self.root.title("Shabbos Sports Score Display (mock)")
        # Prevent window getting huge; keep small to reflect hardware
        self.root.geometry(f"{WIDTH*4}x{HEIGHT*4}") #scale up for visibility on laptop, but will want to NOT scale up after checking that it works
        self.delay_ms = int(delay_seconds * 1000)
        self.results = results or []
        self.idx = 0

        # Create a label to hold the image
        self.img_label = tk.Label(self.root)
        self.img_label.pack(expand=True)

        # Keep reference to PhotoImage to avoid GC (WHAT IS GC?)
        self._photo = None

    def start(self):
        if not self.results:
            # Show a fallback message
            img = self.pil_to_tk(draw_game_image({"type":"message","title":"No games"}))
            self.img_label.config(image = img)
            self.root.after(self.delay_ms, self.root.quit)
        else:
            self.show_next()
            self.root.mainloop()

    def show_next(self):
        card = self.results[self.idx]
        pil_img = draw_game_image(card)

        # Scale the image up for laptop visibility, keeping aspect ratio (AFTER VERIFYING THE DISPLAY I WILL WANT TO KEEP SAME SCALE AS HARDWARE)
        try:
            scaled = pil_img.resize((WIDTH*4, HEIGHT*4), Image.Resampling.NEAREST)
        except AttributeError:
            # Fallback for older Pillow
            scaled = pil_img.resize((WIDTH*2, HEIGHT*2), Image.NEAREST)
        tk_img = self.pil_to_tk(scaled)

        self.img_label.config(image=tk_img)
        self._photo = tk_img    # Keep ref

        # Advance index
        self.idx = (self.idx + 1) % len(self.results)
        # Schedule next update
        self.root.after(self.delay_ms, self.show_next)

    @staticmethod
    def pil_to_tk(pil_img):
        return ImageTk.PhotoImage(pil_img)
       
def main():
    fetcher = DataFetcher()
    results = get_results(fetcher)     # The list of dicts
    # Optional debug:
    print(f"Got {len(results)} cards from get_results()")
    win = DisplayWindow(results, delay_seconds=DISPLAY_TIME)
    win.start()
    #for game in results:
    #    draw_card(game)

if __name__ == "__main__":
    main()