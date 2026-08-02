from __future__ import annotations

# Importing dashboard renders the existing Command Centre in Streamlit.
import dashboard  # noqa: F401,E402

from dashboard_adaptation import render_adaptation_dashboard
from dashboard_jaxter import render_jaxter_dashboard

render_adaptation_dashboard()
render_jaxter_dashboard()
