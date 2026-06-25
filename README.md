# Inhabit — marketing site

A single-page marketing site for **Inhabit**, an open-source teleoperation hardware and
software project for collecting high-quality robot manipulation data.

Pure static files — **no build step required**. Just `index.html`, `style.css`, and `script.js`.

```
inhabitwebsite/
├── index.html      # markup + all sections
├── style.css       # design system (dark, technical, 8px grid)
├── script.js       # scroll reveal, sticky nav, card spotlight
├── .nojekyll        # tells GitHub Pages to skip Jekyll processing
└── README.md
```

## Local preview

No tooling needed — open `index.html` in a browser, or serve it for clean relative paths:

```bash
# Python 3
python -m http.server 8080
# then visit http://localhost:8080
```

## Deploy to GitHub Pages

1. Create a repo and push these files to the `main` branch:

   ```bash
   git init
   git add .
   git commit -m "Inhabit marketing site"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```

2. In the repo, go to **Settings → Pages**.
3. Under **Build and deployment → Source**, choose **Deploy from a branch**.
4. Select branch **`main`** and folder **`/ (root)`**, then **Save**.
5. Wait ~1 minute. Your site will be live at:

   ```
   https://<you>.github.io/<repo>/
   ```

The included `.nojekyll` file ensures GitHub Pages serves all files as-is (no Jekyll build).

### Custom domain (optional)

Add a `CNAME` file containing your domain (e.g. `inhabit.dev`) and configure DNS per
[GitHub's docs](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site).

## Customizing

- **Accent color** — change `--accent` in `style.css` (`:root`). Currently electric blue (`#5b8cff`).
- **Type scale** — all sizes live in the `:root` `--fs-*` variables. Space Grotesk (display) + Inter (body) load from Google Fonts.
- **Copy & links** — edit `index.html`. Replace the placeholder `https://github.com/` and `hello@inhabit.dev` with real destinations.
- **Spacing** — everything is on an 8px grid via the `--s1…--s9` variables.

## Notes

- Respects `prefers-reduced-motion` — all animation is disabled for users who opt out.
- Responsive and intentional from 375px to 1440px+.
- No dependencies, no tracking, no JS frameworks.
