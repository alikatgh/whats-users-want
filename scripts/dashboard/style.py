"""Presentation styling for the Streamlit dashboard."""
from __future__ import annotations

import streamlit as st


def apply_dashboard_style() -> None:
    """Apply a restrained executive-dashboard visual treatment."""
    st.markdown(
        """
        <style>
        :root {
            --wwu-bg: var(--background-color, #ffffff);
            --wwu-bg-soft: var(--secondary-background-color, #f8fafc);
            --wwu-panel-bg: var(--background-color, #ffffff);
            --wwu-ink: var(--text-color, #17202a);
            --wwu-muted: color-mix(in srgb, var(--text-color, #17202a), transparent 34%);
            --wwu-line: color-mix(in srgb, var(--text-color, #17202a), transparent 78%);
            --wwu-soft: var(--secondary-background-color, #f6f8fb);
            --wwu-soft-2: color-mix(in srgb, var(--primary-color, #1f5eff), transparent 88%);
            --wwu-blue: var(--primary-color, #1f5eff);
            --wwu-teal: #007f7a;
            --wwu-amber: #a35b00;
            --wwu-info-bg: color-mix(in srgb, var(--primary-color, #1f5eff), var(--background-color, #ffffff) 86%);
            --wwu-info-text: var(--text-color, #17202a);
            --wwu-decision-bg: color-mix(in srgb, #f59e0b, var(--background-color, #ffffff) 88%);
            --wwu-shadow: 0 1px 2px rgba(17, 24, 39, 0.04);
        }

        .stApp {
            background: var(--wwu-bg);
            color: var(--wwu-ink) !important;
        }

        .block-container {
            max-width: 1320px;
            padding-top: 2.1rem;
            padding-bottom: 4rem;
        }

        h1, h2, h3,
        .wwu-lede,
        .wwu-panel,
        .wwu-callout {
            letter-spacing: 0;
            color: var(--wwu-ink) !important;
        }

        h1 {
            font-size: 2.15rem;
            line-height: 1.12;
            margin-bottom: 0.35rem;
        }

        h2 {
            margin-top: 1.45rem;
            padding-top: 0.25rem;
        }

        div[data-testid="stMetric"] {
            background: var(--wwu-panel-bg);
            border: 1px solid var(--wwu-line);
            border-radius: 8px;
            padding: 0.85rem 0.95rem;
            box-shadow: var(--wwu-shadow);
        }

        div[data-testid="stMetricLabel"] p {
            color: var(--wwu-muted) !important;
            font-size: 0.78rem;
            letter-spacing: 0;
            opacity: 1 !important;
        }

        div[data-testid="stMetricLabel"],
        div[data-testid="stMetricLabel"] *,
        div[data-testid="stMetricValue"],
        div[data-testid="stMetricValue"] *,
        div[data-testid="stMetricDelta"],
        div[data-testid="stMetricDelta"] * {
            opacity: 1 !important;
        }

        div[data-testid="stMetricValue"] {
            color: var(--wwu-ink) !important;
            font-weight: 720;
        }

        div[data-testid="stInfo"] {
            border-radius: 8px;
            border: 1px solid color-mix(in srgb, var(--wwu-blue), transparent 65%);
            background-color: var(--wwu-info-bg) !important;
            color: var(--wwu-info-text) !important;
        }

        div[data-testid="stInfo"] * {
            color: var(--wwu-info-text) !important;
            opacity: 1 !important;
        }

        .wwu-eyebrow {
            color: color-mix(in srgb, var(--wwu-teal), var(--wwu-ink) 20%);
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 0.2rem;
        }

        .wwu-lede {
            color: var(--wwu-muted);
            font-size: 1.02rem;
            line-height: 1.55;
            max-width: 920px;
            margin-bottom: 1rem;
        }

        .wwu-panel {
            background: var(--wwu-panel-bg);
            border: 1px solid var(--wwu-line);
            border-radius: 8px;
            padding: 1rem 1.1rem;
            margin-top: 0.35rem;
            margin-bottom: 1rem;
            box-shadow: var(--wwu-shadow);
            min-height: 132px;
        }

        .wwu-panel h3 {
            margin-top: 0;
            margin-bottom: 0.4rem;
            font-size: 1rem;
        }

        .wwu-panel p, .wwu-panel li {
            color: var(--wwu-muted);
            font-size: 0.91rem;
            line-height: 1.48;
        }

        .wwu-callout {
            background: var(--wwu-panel-bg);
            border-left: 4px solid var(--wwu-blue);
            border-top: 1px solid var(--wwu-line);
            border-right: 1px solid var(--wwu-line);
            border-bottom: 1px solid var(--wwu-line);
            border-radius: 8px;
            padding: 0.95rem 1.05rem;
            margin-top: 0.85rem;
            margin-bottom: 1.25rem;
            color: var(--wwu-ink);
        }

        .wwu-callout strong {
            color: var(--wwu-ink) !important;
        }

        .wwu-decision {
            border-left-color: var(--wwu-amber);
            background: var(--wwu-decision-bg);
        }

        .wwu-small {
            color: var(--wwu-muted);
            font-size: 0.82rem;
            line-height: 1.45;
        }

        section[data-testid="stSidebar"] {
            border-right: 1px solid var(--wwu-line);
        }

        section[data-testid="stSidebar"] a,
        section[data-testid="stSidebar"] button {
            border-radius: 7px !important;
        }

        section[data-testid="stSidebar"] [aria-current="page"],
        section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] {
            background: var(--wwu-soft-2) !important;
        }

        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] > div,
        input, textarea {
            background: var(--wwu-panel-bg) !important;
            color: var(--wwu-ink) !important;
            border-color: var(--wwu-line) !important;
        }

        div[data-testid="stDataFrame"] {
            border: 1px solid var(--wwu-line);
            border-radius: 8px;
            overflow: hidden;
        }

        button[kind="primary"], button[kind="secondary"] {
            border-radius: 7px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
