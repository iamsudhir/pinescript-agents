"""Strategy Workbench. Run from the repo folder: streamlit run app.py"""
import streamlit as st

st.set_page_config(page_title="Strategy Workbench", layout="wide")
st.navigation([
    st.Page("ui/library.py", title="Library", default=True),
    st.Page("ui/create.py", title="Create"),
    st.Page("ui/strategy.py", title="Strategy"),
]).run()
