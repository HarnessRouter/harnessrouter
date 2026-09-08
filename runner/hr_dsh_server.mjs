/**
 * hr-sdk-jsonrpc-server — the upstream SDK server with one override: RESUME-OR-CREATE.
 *
 * Upstream's HarnessSdkJsonRpcServer only ever calls ctx.agents.create(), and the persistence
 * coordinator refuses a create whose sessionId already has a persisted log (a fresh process has
 * no in-memory seed, so adoption cannot apply). That makes every cross-process follow-up die
 * with "persisted log on disk that does not match this live session (id collision)" — captured
 * live on 2026-08-20 against 0.1.0-rc.7 and again on 2026-09-08 against 0.1.2-rc.1. The wire
 * itself has no resume method, so the fix lives at the one seam upstream left open: this file
 * loads as a plugin row inserted by the driver's patch overlay (the stock server row is
 * disabled beside it), subclasses the exported server class from the bundled snapshot, and
 * tries ctx.agents.resume({resumeSessionId}) before falling back to the parent's create.
 *
 * Version-locked: refuses to boot against any other upstream version, loudly, because this
 * reaches into TS-private fields (this.ctx / this.provider / this.model / this.reasoningEffort /
 * this.maxTokens / this.sessions) that only exist by compiled-JS convention.
 *
 * An ES module on purpose: the snapshot's packages are ESM and the loader imports plugin rows
 * concurrently, so a CommonJS require() of @deepseek-ai/dsh-session raced a load already in
 * flight (ERR_REQUIRE_ESM_RACE_CONDITION, measured 2026-09-08). import() waits for it instead.
 */
import path from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

// This file lives OUTSIDE the runtime's snapshot, so a bare '@deepseek-ai/*' specifier cannot
// resolve from here. A require anchored INSIDE the snapshot's node_modules resolves the paths;
// the modules themselves are then imported, the way the loader loads them. The anchor is
// derived from the running entry script (…/node_modules/@deepseek-ai/dsh/lib/bin.js).
const entry = process.argv[1] || ''
const nmIdx = entry.lastIndexOf('node_modules')
if (nmIdx < 0) {
  throw new Error(`hr-sdk-jsonrpc-server: cannot locate the runtime's node_modules from entry '${entry}'`)
}
const nmRoot = entry.slice(0, nmIdx + 'node_modules'.length)
const sreq = createRequire(path.join(nmRoot, 'hr-anchor.js'))
const load = async (name) => {
  let file
  try {
    file = sreq.resolve(name)
  } catch {
    file = path.join(nmRoot, name, 'lib', 'index.js')   // an import-only exports map: the compiled entry
  }
  return import(pathToFileURL(file).href)
}
const base = await load('@deepseek-ai/dsh-sdk-jsonrpc-server')
const { SessionId } = await load('@deepseek-ai/dsh-session')
const { JsonRpcLineTransport } = await load('@deepseek-ai/dsh-sdk-protocol')

const PINNED = '0.1.2-rc.1'   // the repo-wide version the runtime wheel bundles
const got = sreq('@deepseek-ai/dsh-sdk-jsonrpc-server/package.json').version
if (got !== PINNED) {
  throw new Error(`hr-sdk-jsonrpc-server is pinned to @deepseek-ai/dsh-sdk-jsonrpc-server@${PINNED} ` +
                  `but the runtime bundles ${got} — re-verify the private-field override before bumping`)
}

class HrServer extends base.HarnessSdkJsonRpcServer {
  async createSession(sessionId) {
    try {
      const handle = await this.ctx.agents.resume({
        resumeSessionId: SessionId(sessionId),
        agentOptions: {
          provider: this.provider,
          model: this.model,
          ...this.reasoningEffort === undefined ? {} : { reasoningEffort: this.reasoningEffort },
          ...this.maxTokens === undefined ? {} : { maxTokens: this.maxTokens },
        },
      })
      const rec = { handle }
      this.sessions.set(sessionId, rec)
      process.stderr.write(`[hr-dsh] resumed session ${sessionId}\n`)
      return rec
    } catch (e) {
      // Nothing stored (a fresh id), or resume genuinely failed: fall through to the parent's
      // create. A create that then collides surfaces the collision rather than hiding it.
      process.stderr.write(`[hr-dsh] resume miss for ${sessionId}: ${String(e && e.message || e).slice(0, 160)}\n`)
      return super.createSession(sessionId)
    }
  }
}

export const name = 'hr-sdk-jsonrpc-server'
export const inject = ['agents']

export function apply(ctx, config) {
  const rootFiber = ctx.root.fiber
  const transport = new JsonRpcLineTransport(process.stdin, process.stdout)
  const server = new HrServer(ctx, transport, {
    maxTokensAsSuccess: !!(config && config.maxTokensAsSuccess),
  })
  let exitTask
  const disposeAndExit = () => {
    exitTask ??= (async () => {
      await Promise.allSettled([Promise.resolve().then(() => transport.flush())])
      await Promise.allSettled([Promise.resolve().then(() => rootFiber.dispose())])
      process.exit(0)
    })()
    return exitTask
  }
  transport.onRequest(async (method, params) => {
    if (method === 'initialize') await ctx.get('loader')?.await()
    const result = await server.handleRequest(method, params)
    if (method === 'shutdown') setImmediate(() => { void disposeAndExit() })
    return result
  })
  ctx.effect(() => {
    transport.start()
    return async () => {
      await server.shutdown()
      transport.close()
    }
  }, 'hr-jsonrpc.serve')
}
