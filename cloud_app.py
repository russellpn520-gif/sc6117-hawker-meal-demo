import sqlite3

import streamlit as st

from app import main


if __name__ == "__main__":
    try:
        main(public_demo=True)
    except sqlite3.Error:
        st.error("暂时无法读写本次会话的记餐记录，请稍后重试。")
