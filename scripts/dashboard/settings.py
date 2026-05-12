"""Local dashboard settings — flip flags here to control what is shown.

Edit this file in place. The dashboard reads it on every rerun, so changes
take effect as soon as you save (no restart needed).

Tip: keep this file out of any public repo or screenshare if the flags below
are sensitive.
"""

#: When False, the "How managers compare" page is **hidden from the sidebar**
#: and removed from the navigation entirely. The home-page bullet that names
#: a specific manager is also hidden, and the manager-quality page itself
#: refuses to render even if someone navigates to its URL directly.
#:
#: Set to True before sharing the dashboard with the broader team if you want
#: the manager-comparison work visible. Set to False (default) when
#: presenting findings without naming people.
SHOW_MANAGER_COMPARISONS = False

#: When False, the home-page bullet about diamond/dealer disputes is hidden.
#: Useful if the audience hasn't seen that finding yet and you want to lead
#: with something else. Default True.
SHOW_DIAMOND_DEALER_FINDING = True

#: When False, the printable executive summary section on the home page is
#: hidden. Useful if you're sharing the dashboard live and don't want
#: viewers to download a frozen snapshot. Default True.
SHOW_EXECUTIVE_EXPORT = True

#: When False, the Tools section is removed from the sidebar — Start
#: Extraction, Live extraction monitor, and Run SQL queries all disappear.
#: Useful when sharing with a non-technical audience. Default True.
SHOW_TOOLS_SECTION = True
