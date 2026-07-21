import './RequirementsChangedBanner.css'

export interface RequirementsChange {
  /** Version the candidate was working against before the push. */
  previousVersionId: string
  /** Version now in force; submissions grade against this one. */
  newVersionId: string
  summary: string
}

interface RequirementsChangedBannerProps {
  change?: RequirementsChange | null
  onDismiss?: () => void
}

/**
 * Phase 2 surface, built and tested now so the exam room has the seam ready.
 * A proctor pushing a mid-exam constraint change creates a NEW question
 * version; this banner tells the candidate their requirements moved.
 *
 * Phase 1 never supplies a `change`, so it renders nothing.
 */
export function RequirementsChangedBanner({
  change,
  onDismiss,
}: RequirementsChangedBannerProps) {
  if (!change) return null

  return (
    <div className="requirements-banner" role="alert">
      <div>
        <strong className="requirements-banner__title">
          The requirements for this question changed
        </strong>
        <p className="requirements-banner__summary">{change.summary}</p>
      </div>
      {onDismiss && (
        <button
          type="button"
          className="requirements-banner__dismiss"
          onClick={onDismiss}
        >
          Dismiss
        </button>
      )}
    </div>
  )
}
