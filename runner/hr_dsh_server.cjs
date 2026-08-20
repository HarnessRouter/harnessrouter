/**
 * hr-sdk-jsonrpc-server — the upstream SDK server with one override: RESUME-OR-CREATE.
 *
 * Upstream's HarnessSdkJsonRpcServer only ever calls ctx.agents.create(), and the persistence
 * coordinator refuses a create whose sessionId already has a persisted log (a fresh process has
 * no in-memory seed, so adoption cannot apply). That makes every cross-process follow-up die
 * with "persisted log on disk that does not match this live session (id collision)" — captured
 * live on 2026-08-20, and precisely the continuation gap the DeepSeek-Harness audit predicted.
 * The wire itself has no resume method, so the fix lives at the one seam upstream left open:
 * this file loads as a CONFIGURATION-RELATIVE plugin (a documented packaged-bin feature),
 * subclasses the exported server class from the bundled snapshot, and tries
 * ctx.agents.resume({resumeSessionId}) before falling back to the parent's create.
 *
 * Version-locked: refuses to boot against any other upstream version, loudly, because this
 * reaches into TS-private fields (this.ctx / this.provider / this.model / this.maxTokens)
 * that only exist by compiled-JS convention.
 */
'use strict'

// This file lives OUTSIDE the runtime's pkg snapshot, so its own require cannot resolve the
// bundled '@deepseek-ai/*' modules. The snapshot's patched fs is process-global though, so a
// createRequire anchored INSIDE the snapshot's node_modules resolves them fine. The anchor is
// derived from the running entry script (…/node_modules/@deepseek-ai/dsh-sdk-jsonrpc-demo/lib/
// packaged-bin.js), which holds for both runtime carriers.
const path = require('node:path')
const { createRequire } = require('node:module')
const entry = process.argv[1] || ''
const nmIdx = entry.lastIndexOf('node_modules')
if (nmIdx < 0) {
  throw new Error(`hr-sdk-jsonrpc-server: cannot locate the runtime's node_modules from entry '${entry}'`)
}
const sreq = createRequire(path.join(entry.slice(0, nmIdx + 'node_modules'.length), 'hr-anchor.js'))
const base = sreq('@deepseek-ai/dsh-sdk-jsonrpc-server')
const { SessionId } = sreq('@deepseek-ai/dsh-session')
const { JsonRpcLineTransport } = sreq('@deepseek-ai/dsh-sdk-protocol')

const PINNED = '0.1.0-rc.7'   // the repo-wide version the runtime wheel bundles
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

exports.name = 'hr-sdk-jsonrpc-server'
exports.inject = ['agents']

exports.apply = function apply(ctx, config) {
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
