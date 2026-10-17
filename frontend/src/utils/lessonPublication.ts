import type { AgentRun } from '../api/agents'

export function pptPublicationState(run: AgentRun | null) {
  const output = run?.output_data
  const artifact = output?.artifacts?.ppt
  const ppt = output?.artifact_bundle?.ppt
  const attempt = output?.artifact_attempt
  const revision = artifact?.revision_id || ppt?.revision_id || ''
  const previous = artifact?.requires_previous_confirmation ?? Boolean(
    artifact && (output?.artifact_errors?.ppt || (
      attempt?.requested_types?.includes('ppt')
      && ['queued', 'running', 'failed', 'partial'].includes(attempt.status)
      && artifact.attempt_id !== attempt.id
    )),
  )
  const valid = Boolean(artifact
    && (ppt?.pipeline_version !== 'ppt-master-svg-v2' || revision)
    && !(artifact.revision_id && ppt?.revision_id && artifact.revision_id !== ppt.revision_id))
  return { revision, previous, valid }
}
