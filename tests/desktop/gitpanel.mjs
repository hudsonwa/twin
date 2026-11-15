// Git history: the Twins page's per-twin switch, optional remote and last commit/push status, outside Hermes Desktop.
//
//   node tests/desktop/gitpanel.mjs [--modules DIR]
//
// DIR is a node_modules folder holding react + react-dom (19.x). A temp copy of desktop/plugin.js gets its three
// bare imports rewritten to local shims (a small stub of @hermes/plugin-sdk and the real React), as memory.mjs
// does; this file only knows the "What syncs" fold. Invented data only, and every invented answer is checked
// against tests/desktop/gitpanel_shapes.json first, so the page is never tested against an answer that cannot come.
//
// The render is a static one, so what a press changes cannot be read back from the screen. Each act is checked
// in two halves that share one object: the press is made and what it hands back (the sentence to say, or the
// problem) is looked at, and then the panel is drawn with exactly that.

import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(here, '../../desktop/plugin.js'), 'utf8')
const SHAPES = JSON.parse(readFileSync(resolve(here, 'gitpanel_shapes.json'), 'utf8')).shapes
const argModules = process.argv.indexOf('--modules')
const modulesDir = argModules > 0 ? resolve(process.argv[argModules + 1]) : resolve(here, '../../node_modules')

let passed = 0
const ok = (cond, msg) => {
  assert.ok(cond, msg)
  passed += 1
}

if (!existsSync(join(modulesDir, 'react/package.json')) || !existsSync(join(modulesDir, 'react-dom/package.json'))) {
  console.log('gitpanel check: skipped (no react / react-dom in the modules folder)')
  process.exit(0)
}

// ── 1. shims ────────────────────────────────────────────────────────────────

const work = mkdtempSync(join(tmpdir(), 'twin-git-'))
// (the temp copy goes away however the run ends)
process.on('exit', () => rmSync(work, { force: true, recursive: true }))
const req = createRequire(join(modulesDir, 'x.js'))

function shim(file, mod) {
  const keys = Object.keys(req(mod)).filter(k => /^[A-Za-z_$][\w$]*$/.test(k) && k !== 'default')

  writeFileSync(join(work, file), `import { createRequire } from 'node:module'\nconst m = createRequire(${JSON.stringify(join(modulesDir, 'x.js'))})(${JSON.stringify(mod)})\nexport default m\nexport const { ${keys.join(', ')} } = m\n`)
}

shim('react.mjs', 'react')
shim('jsx.mjs', 'react/jsx-runtime')

const sdkNames = source
  .match(/import\s*\{([^}]+)\}\s*from\s*'@hermes\/plugin-sdk'/)[1]
  .split(',')
  .map(s => s.trim())
  .filter(Boolean)
const special = {
  Button: `({ children, disabled, loading, onClick, ...p }) => { H.buttons.push({ text: H.text(children), label: p['aria-label'], expanded: p['aria-expanded'], describedBy: p['aria-describedby'], onClick, disabled: Boolean(disabled || loading), variant: p.variant ?? 'default' }); return jsx('button', { disabled: Boolean(disabled || loading), 'aria-label': p['aria-label'], 'aria-expanded': p['aria-expanded'], 'aria-describedby': p['aria-describedby'], children }) }`,
  Switch: `p => { H.switches.push({ checked: p.checked, disabled: p.disabled, id: p.id, label: p['aria-label'], onCheckedChange: p.onCheckedChange }); return jsx('button', { role: 'switch', 'aria-checked': p.checked, 'aria-label': p['aria-label'], 'aria-describedby': p['aria-describedby'], disabled: p.disabled, id: p.id }) }`,
  cn: `(...a) => a.flat(Infinity).filter(Boolean).join(' ')`,
  host: `H.host`,
  queryClient: `H.queryClient`,
  relativeTime: `ms => { const m = Math.round((Date.now() - ms) / 60000); return m < 1 ? 'just now' : m + ' min ago' }`,
  useQuery: `opts => H.useQuery(opts)`,
  useQueryClient: `() => H.queryClient`,
  PALETTE_AREA: `'palette'`,
  ROUTES_AREA: `'routes'`,
  SIDEBAR_NAV_AREA: `'sidebar.nav'`,
  STATUSBAR_AREAS: `{ left: 'statusBar.left', right: 'statusBar.right' }`
}
const pass = `({ children, className }) => jsx('div', { className, children })`

writeFileSync(
  join(work, 'sdk.mjs'),
  `import { jsx } from './jsx.mjs'\nconst H = globalThis.__h\n` + sdkNames.map(n => `export const ${n} = ${special[n] ?? pass}`).join('\n') + '\n'
)
writeFileSync(
  join(work, 'plugin.mjs'),
  source
    .replace(/from\s*'@hermes\/plugin-sdk'/, `from './sdk.mjs'`)
    .replace(/from\s*'react\/jsx-runtime'/, `from './jsx.mjs'`)
    .replace(/from\s*'react'/, `from './react.mjs'`)
    .concat('\nexport const __git = { GitFold, GitPanel, gitPanelOf }\n')
)

// the page's clock stands at 09:03 on 1 Jan 2000, three minutes after the invented last sync
const NOW = Date.parse('2000-01-01T09:03:00Z')
Date.now = () => NOW

const H = (globalThis.__h = {
  buttons: [],
  switches: [],
  options: [],
  notes: [],
  restCalls: [],
  restReply: async () => ({}),
  setData: [],
  invalidated: 0,
  panel: undefined,
  queries: [],
  text: c => (Array.isArray(c) ? c.map(H.text).join('') : typeof c === 'string' || typeof c === 'number' ? String(c) : c?.props?.children ? H.text(c.props.children) : ''),
  host: { notify: n => H.notes.push(n), navigate: () => {}, state: { profile: { get: () => 'default' }, gateway: { get: () => 'open' } } },
  queryClient: { getQueryData: () => undefined, setQueryData: (key, value) => H.setData.push([key[1], value]), invalidateQueries: async () => { H.invalidated += 1 } },
  useQuery: opts => {
    H.queries.push(opts)

    return { data: opts.queryKey[1] === 'git-panel' && opts.enabled !== false ? H.panel : undefined, error: null, isError: false, isPending: false, refetch: async () => {} }
  }
})

const mod = await import(pathToFileURL(join(work, 'plugin.mjs')).href)
const P = mod.__git
const { renderToStaticMarkup } = req('react-dom/server')
const { jsx } = req('react/jsx-runtime')

mod.default.register({
  onDispose: () => {},
  onEvent: () => {},
  registerMany: () => {},
  rest: async (path, opts) => {
    H.restCalls.push({ path, opts })

    return H.restReply(path, opts)
  },
  setInterval: () => () => {},
  setTimeout: () => () => {},
  storage: { get: (k, f) => f, remove: () => {}, set: () => {} }
})

const tick = async (n = 3) => {
  for (let i = 0; i < n; i++) {
    await new Promise(r => setImmediate(r))
  }
}
const text = html => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&gt;/g, '>').replace(/&lt;/g, '<').replace(/\s+/g, ' ').trim()
let markup = '' // the last render as it would reach the screen: tags and all
const ACME = 'acme-support'
const RECIPE = 'recipe-planner'
const pairOf = (id, over = {}) => ({ pair_id: id, grok: { name: 'Acme Support' }, hermes: { profile: id }, ...over })
const render = (data, { pair = pairOf(ACME), initialSaid = null, initialRemote = '' } = {}) => {
  H.buttons = []
  H.switches = []
  H.queries = []
  H.panel = data
  markup = renderToStaticMarkup(jsx(P.GitFold, { initialSaid, initialRemote, pair }))

  return text(markup)
}
// a fresh count of everything a press can cause
const quiet = reply => {
  H.restCalls = []
  H.setData = []
  H.notes = []
  H.invalidated = 0
  H.restReply = reply
}
const button = name => H.buttons.filter(b => b.text === name)
const bodyOf = call => JSON.stringify(call?.opts?.body)
const option = (key, direction) => H.options.find(o => o.name === `gbt-sync-${key}` && o.choice.direction === direction)
const optionsOf = key => H.options.filter(o => o.name === `gbt-sync-${key}`)
const between = (from, to) => markup.slice(markup.indexOf(from), to ? markup.indexOf(to, markup.indexOf(from) + 1) : undefined)


// ── 2. shapes ───────────────────────────────────────────────────────────────

function fits(value, type, path) {
  const out = []

  for (const alt of type.split('|')) {
    const list = alt.match(/^list\[(.+)\]$/)

    if (alt === 'null' ? value === null : alt === 'str' ? typeof value === 'string' : alt === 'bool' ? typeof value === 'boolean' : false) {
      return []
    }

    if (list && Array.isArray(value)) {
      return value.flatMap((v, i) => fits(v, list[1], `${path}[${i}]`))
    }

    if (SHAPES[alt] && value && typeof value === 'object' && !Array.isArray(value)) {
      const sh = SHAPES[alt]

      for (const [k, t] of Object.entries(sh.required)) {
        out.push(...(k in value ? fits(value[k], t, `${path}.${k}`) : [`${path}.${k} is missing`]))
      }

      for (const [k, t] of Object.entries(sh.optional ?? {})) {
        if (k in value) {
          out.push(...fits(value[k], t, `${path}.${k}`))
        }
      }

      for (const k of Object.keys(value)) {
        if (sh.closed && !(k in sh.required) && !(k in (sh.optional ?? {}))) {
          out.push(`${path}.${k} is not in the shape`)
        }
      }

      return out
    }
  }

  return [`${path} is not ${type}`]
}

// ── 3. fixtures (invented) ──────────────────────────────────────────────────

const SCHEMA = 'grok-bot-twin.gitpanel.v1'
const twin = (id, name, over = {}) => ({ every: false, id, last: null, name, on: false, remote_host: '', remote_set: false, ...over })
const panel = (twins, over = {}) => ({ git: true, install: '', schema: SCHEMA, twins, ...over })
const off = panel([twin(ACME, 'Acme Support'), twin(RECIPE, 'Recipe Planner')])
const on = panel([twin(ACME, 'Acme Support', { last: { at: '2000-01-01T09:00:00Z', commit: 'a1b2c3d', problem: '', pushed: true }, on: true, remote_host: 'forgejo.example', remote_set: true }), twin(RECIPE, 'Recipe Planner')])
const failed = panel([twin(ACME, 'Acme Support', { last: { at: '2000-01-01T09:00:00Z', commit: 'a1b2c3d', problem: 'The push failed: no route to host', pushed: false }, on: true, remote_host: 'forgejo.example', remote_set: true })])
const noGit = panel([twin(ACME, 'Acme Support')], { git: false, install: 'git is not installed, so no git history was kept (install it: macOS `xcode-select --install`, Debian/Ubuntu `sudo apt install git`)' })

for (const [name, value] of Object.entries({ off, on, failed, noGit, said: { ...on, said: { sentence: 'Git history for Acme Support: on.' } } })) {
  const probs = fits(value, 'GitPanel', name)

  ok(probs.length === 0, `the invented answer "${name}" fits gitpanel_shapes.json: ${probs.join('; ')}`)
}
ok(fits({ ...off, extra: 1 }, 'GitPanel', 'x').length === 1, 'the shape checker catches a key too many')

// ── 4. the read, and when there is nothing ─────────────────────────────────

let html = render(off)
ok(H.queries.length === 1 && H.queries[0].queryKey.join('/') === 'grok-bot-twin/git-panel' && H.queries[0].retry === 1, 'one read of its own')
quiet(async () => off)
await H.queries[0].queryFn()
ok(H.restCalls.length === 1 && H.restCalls[0].path === '/git/panel' && H.restCalls[0].opts === undefined, 'the read is GET /git/panel')
ok(render(undefined) === '' && render({ ...off, schema: 'x' }) === '' && render('junk') === '' && render({ error: { code: 'internal', message: 'x' } }) === '', 'no answer, another schema or a problem: nothing at all')
ok(render(off, { pair: pairOf('someone-else') }) === '' && render(off, { pair: pairOf(ACME, { sample: true }) }) === '' && H.queries[0].enabled === false, 'a twin it does not know, or the sample: nothing, and no read on the sample')

// ── 5. off: a labelled switch, no remote field ─────────────────────────────

html = render(off)
ok(html.includes('Git history') && /<label[^>]*for="gbt-git-acme-support"[^>]*>Git history<\/label>/.test(markup), 'a visible label tied to the switch')
ok(markup.includes('aria-label="Keep a git history of Acme Support"') && markup.includes('aria-describedby="gbt-git-acme-support-says"'), 'the switch is named for its twin and described')
ok(markup.includes('aria-checked="false"'), 'off by default')
ok(!markup.includes('Remote address') && !markup.includes('<form') && !html.includes('Last commit'), 'off: no remote field, no commit line')

// ── 6. on: remote field with its label, host, last commit and push ─────────

html = render(on)
ok(/<label[^>]*for="gbt-git-acme-support-remote"/.test(markup) && markup.includes('id="gbt-git-acme-support-remote"'), 'the remote field has a label')
ok(html.includes('Pushes to forgejo.example') && !html.includes('tok-'), 'a remote that is set says its host only')
ok(html.includes('Last commit 3 min ago (a1b2c3d), pushed.'), `the last commit and push (${html})`)
ok(markup.includes('<button') && button('Save').length === 1 && button('Save')[0].disabled === false, 'with a remote set, Save can clear it')
html = render(failed)
ok(html.includes('not pushed') && html.includes('The push failed: no route to host'), 'a failed push is shown in plain words')
html = render(panel([twin(ACME, 'Acme Support', { on: true })]))
ok(button('Save')[0].disabled === true, 'no remote and nothing typed: Save waits')
ok(html.includes('Nothing kept yet') && html.includes('Remote address (optional)'), 'on, nothing committed yet, no remote')

// ── 7. git missing ─────────────────────────────────────────────────────────

html = render(noGit)
ok(html.includes('git is not installed') && html.includes('xcode-select'), 'git missing: a plain message with how to install it')

// ── 8. presses ──────────────────────────────────────────────────────────────

render(off)
const sw = H.switches.at(-1)
ok(sw && sw.checked === false && sw.id === 'gbt-git-acme-support' && sw.label === 'Keep a git history of Acme Support', 'the switch is off and named')
quiet(async () => ({ ...on, said: { sentence: 'Git history for Acme Support: on.' } }))
await sw.onCheckedChange(true)
await tick()
ok(H.restCalls.length === 1 && H.restCalls[0].path === '/git/panel' && H.restCalls[0].opts.method === 'POST' && bodyOf(H.restCalls[0]) === JSON.stringify({ on: true, twin: ACME }), `on: one POST with the twin and on, no remote (${JSON.stringify(H.restCalls)})`)
ok(H.setData.length === 1 && H.setData[0][0] === 'git-panel', 'the answer is shown at once')
render(on)
quiet(async () => on)

// a refusal: said in the backend's words, the switch is not moved by the page
quiet(async () => { throw Object.assign(new Error('Git is not installed.'), { code: 'no_git' }) })
render(noGit)
await H.switches.at(-1).onCheckedChange(true)
await tick()
ok(H.setData.length === 0, 'a refusal changes nothing on the page')

console.log(`gitpanel check: ${passed} checks passed`)
