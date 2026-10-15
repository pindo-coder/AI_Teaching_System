// Deduplicate identical in-flight lookups, but never drop a newer scope just
// because another lookup is busy. Late successes and failures cannot replace it.
export function createWorkspaceContextLoader<Scope, Context>(options: {
  fetch: (scope: Scope) => Promise<Context>
  onContext: (context: Context | null) => void
  onLoading: (loading: boolean) => void
}) {
  let revision = 0
  let pending: { key: string; promise: Promise<Context | null> } | null = null

  return {
    load(scope: Scope): Promise<Context | null> {
      const key = JSON.stringify(scope)
      if (pending?.key === key) return pending.promise
      const current = ++revision
      options.onLoading(true)
      const promise = Promise.resolve().then(() => options.fetch(scope)).then((context) => {
        if (current !== revision) return null
        options.onContext(context)
        return context
      }).catch(() => {
        if (current === revision) options.onContext(null)
        return null
      }).finally(() => {
        if (current === revision) {
          pending = null
          options.onLoading(false)
        }
      })
      pending = { key, promise }
      return promise
    },
    reset() {
      revision += 1
      pending = null
      options.onContext(null)
      options.onLoading(false)
    },
  }
}
