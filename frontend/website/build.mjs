// Zero-dependency static site builder for the HaemNet public website.
//   node build.mjs           build into dist/ and run the checks
//   node build.mjs --serve   build, then serve dist/ on http://localhost:4000
// Templates: {{ a.b }} value, {{{ raw }}} unescaped, {{> partial }} include,
// {{#if a.b}}...{{else}}...{{/if}} (no nesting).

import { readFileSync, writeFileSync, mkdirSync, readdirSync, cpSync, rmSync, existsSync, statSync } from 'node:fs';
import { join, dirname, extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:http';

const root = dirname(fileURLToPath(import.meta.url));
const src = join(root, 'src');
const dist = join(root, 'dist');

const site = JSON.parse(readFileSync(join(root, 'site.config.json'), 'utf8'));
if (process.env.SITE_URL) site.siteUrl = process.env.SITE_URL.replace(/\/$/, '');
site.year = new Date().getFullYear();

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const lookup = (ctx, path) => path.split('.').reduce((o, k) => (o == null ? o : o[k]), ctx);

const partials = {};
for (const f of readdirSync(join(src, 'partials'))) partials[f.replace(/\.html$/, '')] = readFileSync(join(src, 'partials', f), 'utf8');

function render(tpl, ctx, depth = 0) {
  if (depth > 5) throw new Error('Partials nested too deeply');
  let out = tpl.replace(/\{\{>\s*([\w-]+)\s*\}\}/g, (_, name) => {
    if (!(name in partials)) throw new Error(`Unknown partial: ${name}`);
    return partials[name];
  });
  if (/\{\{>/.test(out)) return render(out, ctx, depth + 1);
  out = out.replace(/\{\{#if ([\w.]+)\}\}([\s\S]*?)(?:\{\{else\}\}([\s\S]*?))?\{\{\/if\}\}/g, (_, key, yes, no = '') => (lookup(ctx, key) ? yes : no));
  out = out.replace(/\{\{\{\s*([\w.]+)\s*\}\}\}/g, (_, key) => String(lookup(ctx, key) ?? ''));
  out = out.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_, key) => {
    const v = lookup(ctx, key);
    if (v === undefined) throw new Error(`Missing template value: ${key}`);
    return v === null ? '' : esc(v);
  });
  return out;
}

function frontMatter(text) {
  const m = text.match(/^---\n([\s\S]*?)\n---\n?/);
  if (!m) return { meta: {}, body: text };
  const meta = {};
  for (const line of m[1].split('\n')) {
    const i = line.indexOf(':');
    if (i < 0) continue;
    const v = line.slice(i + 1).trim();
    meta[line.slice(0, i).trim()] = v === 'true' ? true : v === 'false' ? false : v;
  }
  return { meta, body: text.slice(m[0].length) };
}

function build() {
  rmSync(dist, { recursive: true, force: true });
  mkdirSync(dist, { recursive: true });
  cpSync(join(src, 'static'), dist, { recursive: true });
  cpSync(join(src, 'css'), join(dist, 'css'), { recursive: true });
  cpSync(join(src, 'js'), join(dist, 'js'), { recursive: true });

  const layout = readFileSync(join(src, 'layout.html'), 'utf8').replace('{{{content}}}', '<!--PAGE-CONTENT-->');
  const pages = [];
  const errors = [];
  const warnings = [];

  for (const file of readdirSync(join(src, 'pages')).filter((f) => f.endsWith('.html')).sort()) {
    const slug = file.replace(/\.html$/, '');
    const { meta, body } = frontMatter(readFileSync(join(src, 'pages', file), 'utf8'));
    const path = slug === 'index' ? '/' : `/${slug}`;
    const title = meta.title || '';
    const page = {
      ...meta,
      slug,
      path,
      url: site.siteUrl + (path === '/' ? '/' : path),
      fullTitle: slug === 'index' || /HaemNet/.test(title) ? title : `${title} | HaemNet`,
      ogImage: site.siteUrl + '/og-image.png',
      noindex: Boolean(meta.noindex),
      draft: Boolean(meta.draft),
      ['is_' + slug.replace(/-/g, '_')]: true,
    };
    const ctx = { site, page };
    let html;
    try {
      const inner = render(body, ctx);
      html = render(layout, ctx).replace('<!--PAGE-CONTENT-->', () => inner);
    } catch (e) { errors.push(`${file}: ${e.message}`); continue; }

    if (!title) errors.push(`${file}: missing title`);
    else if (page.fullTitle.length > 65) warnings.push(`${file}: title is ${page.fullTitle.length} chars (aim for 60 or fewer)`);
    const d = meta.description || '';
    if (d.length < 70 || d.length > 165) errors.push(`${file}: description must be 70 to 165 chars (is ${d.length})`);
    if ((html.match(/<h1[ >]/g) || []).length !== 1) errors.push(`${file}: needs exactly one <h1>`);
    for (const img of html.match(/<img\b[^>]*>/g) || []) if (!/\salt=/.test(img)) errors.push(`${file}: image without alt: ${img.slice(0, 60)}`);
    if (page.draft) warnings.push(`${file}: marked draft (shows a review banner). Remove "draft: true" after review.`);

    writeFileSync(join(dist, slug === 'index' ? 'index.html' : `${slug}.html`), html);
    pages.push({ ...page, html });
  }

  const indexable = pages.filter((p) => !p.noindex && p.slug !== '404');
  const lastmod = new Date().toISOString().slice(0, 10);
  writeFileSync(join(dist, 'sitemap.xml'),
    `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n` +
    indexable.map((p) => `  <url><loc>${p.url}</loc><lastmod>${lastmod}</lastmod></url>`).join('\n') + `\n</urlset>\n`);
  writeFileSync(join(dist, 'robots.txt'), `User-agent: *\nAllow: /\nDisallow: /thank-you\n\nSitemap: ${site.siteUrl}/sitemap.xml\n`);
  writeFileSync(join(dist, 'site.webmanifest'), JSON.stringify({
    name: site.name, short_name: site.name, description: site.tagline, start_url: '/', display: 'browser',
    background_color: '#F5F7FA', theme_color: '#0F1A2B',
    icons: [{ src: '/icon-192.png', sizes: '192x192', type: 'image/png' }, { src: '/icon-512.png', sizes: '512x512', type: 'image/png' }],
  }, null, 2));

  // Link check: every internal href/src must resolve to a built file.
  const exists = (p) => {
    const clean = p.split('#')[0].split('?')[0];
    if (clean === '' || clean === '/') return true;
    const rel = clean.replace(/^\//, '');
    return [rel, rel + '.html', join(rel, 'index.html')].some((c) => existsSync(join(dist, c)) && statSync(join(dist, c)).isFile());
  };
  for (const p of pages) {
    for (const m of p.html.matchAll(/(?:href|src)="(\/[^"]*)"/g)) if (!exists(m[1])) errors.push(`${p.slug}.html: broken link ${m[1]}`);
    for (const m of p.html.matchAll(/href="#([^"]+)"/g)) if (!p.html.includes(`id="${m[1]}"`)) errors.push(`${p.slug}.html: missing anchor #${m[1]}`);
    if (/lorem ipsum|TODO|placeholder text/i.test(p.html.replace(/placeholder="[^"]*"/g, ''))) errors.push(`${p.slug}.html: leftover placeholder text`);
  }

  console.log(`Built ${pages.length} pages into dist/ for ${site.siteUrl}`);
  for (const w of warnings) console.warn('  warning:', w);
  if (errors.length) { for (const e of errors) console.error('  ERROR:', e); process.exit(1); }
}

build();

if (process.argv.includes('--serve')) {
  const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.xml': 'application/xml', '.txt': 'text/plain', '.webmanifest': 'application/manifest+json' };
  const port = Number(process.env.PORT) || 4000;
  createServer((req, res) => {
    let p = decodeURIComponent(req.url.split('?')[0]);
    if (p.includes('..')) { res.writeHead(400).end(); return; }
    const tries = p === '/' ? ['index.html'] : [p.slice(1), p.slice(1) + '.html'];
    const hit = tries.find((t) => existsSync(join(dist, t)) && statSync(join(dist, t)).isFile());
    const file = hit ?? '404.html';
    res.writeHead(hit ? 200 : 404, { 'Content-Type': types[extname(file)] || 'application/octet-stream' });
    res.end(readFileSync(join(dist, file)));
  }).listen(port, () => console.log(`Serving dist/ at http://localhost:${port}`));
}
