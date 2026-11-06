"""Create page: a new strategy from a YouTube video, a description, or an existing .pine file."""
import streamlit as st

from workbench import ROOT, actions, db, generate

conn = db.connect()
st.title("Create a strategy")

if not generate.has_credentials():
    st.warning("Claude needs an API key. Create a file named `.env` in the repo folder containing\n\n"
               "`ANTHROPIC_API_KEY=sk-ant-...`\n\nand restart the app. To try the app without a key, "
               "start it with the environment variable `WORKBENCH_DRY_RUN=1`.")
    st.stop()


def create(label, make):
    """Run make() (returns a strategy id) inside a status box, then open the new strategy."""
    with st.status(label) as box:
        try:
            sid = make()
        except Exception as e:
            box.update(label="Failed", state="error")
            st.error(str(e))
            return
    st.session_state.strategy_id = sid
    st.switch_page("ui/strategy.py")


url_tab, desc_tab, pine_tab = st.tabs(["YouTube URL", "Description", "Import .pine"])

with url_tab:
    url = st.text_input("YouTube URL", placeholder="https://www.youtube.com/watch?v=...")
    if st.button("Generate from video", type="primary", disabled=not url.strip()):
        create("Fetching the transcript and writing Pine + Python, usually 1-3 minutes...",
               lambda: actions.create_from(conn, generate.from_youtube(url.strip()), "youtube"))

with desc_tab:
    desc = st.text_area("Describe the strategy", height=200, placeholder=(
        "RSI(2) mean reversion on Nifty: buy when RSI(2) < 10 and close > 200 EMA; "
        "exit when close crosses above the 5 SMA; 3% stop."))
    if st.button("Generate from description", type="primary", disabled=not desc.strip()):
        create("Writing Pine + Python, usually 1-3 minutes...",
               lambda: actions.create_from(conn, generate.from_description(desc), "description"))

with pine_tab:
    done = db.sources(conn, "pine_import")
    files = sorted((ROOT / "projects").glob("*.pine"))
    st.caption("Indicators can be imported too: Claude turns their signals into entries and exits "
               "and says so in the notes.")
    pick = st.selectbox("Script from projects/", files,
                        format_func=lambda p: p.name + ("  (imported)" if actions.rel(p) in done else ""))
    if st.button("Import selected", type="primary", disabled=pick is None):
        create(f"Writing the Python version of {pick.name}...", lambda: actions.import_pine(conn, pick))
    todo = [p for p in files if actions.rel(p) not in done]
    if st.button(f"Import all not yet imported ({len(todo)})", disabled=not todo):
        bar = st.progress(0.0)
        for i, p in enumerate(todo):
            bar.progress(i / len(todo), text=f"{p.name} ({i + 1}/{len(todo)})")
            try:
                actions.import_pine(conn, p)
            except Exception as e:
                st.error(f"{p.name}: {e}")
        bar.progress(1.0, text="Done. Open the Library to see them.")
