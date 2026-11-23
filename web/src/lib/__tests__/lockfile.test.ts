import lock from '../../../package-lock.json'

type Entry = {
  link?: boolean
  dependencies?: Record<string, string>
  optionalDependencies?: Record<string, string>
  peerDependencies?: Record<string, string>
  peerDependenciesMeta?: Record<string, { optional?: boolean }>
}

/** Dependencies an entry needs that node's lookup (walking up node_modules) can't find. */
function unresolved(packages: Record<string, Entry>): string[] {
  const missing: string[] = []
  for (const [key, entry] of Object.entries(packages)) {
    if (entry.link) continue
    const needs = new Set([...Object.keys(entry.dependencies ?? {})])
    for (const peer of Object.keys(entry.peerDependencies ?? {})) {
      if (!entry.peerDependenciesMeta?.[peer]?.optional) needs.add(peer)
    }
    for (const name of needs) {
      let base = key
      let found = false
      for (;;) {
        if (packages[(base ? base + '/' : '') + 'node_modules/' + name]) { found = true; break }
        if (!base) break
        const at = base.lastIndexOf('/node_modules/')
        base = at < 0 ? '' : base.slice(0, at)
      }
      if (!found) missing.push(name + ' needed by ' + (key || 'the app'))
    }
  }
  return missing
}

describe('package-lock.json', () => {
  // The image installs with npm 10 (node:22). npm 11 can write a lockfile that leaves a needed
  // package only inside another package's bundle; npm 10 then refuses `npm ci` (EUSAGE) and the
  // deploy fails. Regenerate with `npx npm@10 install --package-lock-only` if this fails.
  it('lets every package resolve its dependencies, as npm 10 requires', () => {
    expect(unresolved((lock as unknown as { packages: Record<string, Entry> }).packages)).toEqual([])
  })
})
