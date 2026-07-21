import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { RequirementsChangedBanner } from './RequirementsChangedBanner'

describe('RequirementsChangedBanner', () => {
  it('renders nothing in Phase 1, where no change is ever pushed', () => {
    const { container } = render(<RequirementsChangedBanner change={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('announces a pushed requirements change (Phase 2 seam)', () => {
    render(
      <RequirementsChangedBanner
        change={{
          previousVersionId: 'v1',
          newVersionId: 'v2',
          summary: 'n can now be up to 10^6.',
        }}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent(
      /requirements for this question changed/i,
    )
    expect(screen.getByText('n can now be up to 10^6.')).toBeInTheDocument()
  })

  it('can be dismissed when a handler is supplied', async () => {
    const onDismiss = vi.fn()
    render(
      <RequirementsChangedBanner
        change={{ previousVersionId: 'v1', newVersionId: 'v2', summary: 'x' }}
        onDismiss={onDismiss}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: /dismiss/i }))
    expect(onDismiss).toHaveBeenCalledOnce()
  })
})
