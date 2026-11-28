"""Streamlit Community Cloud entry point for the public mobile diary."""
from app import run_diary


if __name__ == "__main__":
    run_diary(public_demo=True)
