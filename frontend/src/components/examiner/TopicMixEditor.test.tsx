import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'

import type { Topic, TopicMixEntry } from '../../api/examiner/types'
import {
  emptyEntry,
  TopicMixEditor,
  totalWeight,
  validateTopicMix,
} from './TopicMixEditor'

const TOPICS: Topic[] = [
  { id: 't1', org_id: 'o', name: 'arrays', parent_id: null, created_at: '' },
  { id: 't2', org_id: 'o', name: 'graphs', parent_id: null, created_at: '' },
]

function entry(overrides: Partial<TopicMixEntry> = {}): TopicMixEntry {
  return { ...emptyEntry(), topic_id: 't1', ...overrides }
}

/** Stateful harness so edits flow back in, as they do on the page. */
function Harness({ initial }: { initial: TopicMixEntry[] }) {
  const [entries, setEntries] = useState(initial)
  return <TopicMixEditor topics={TOPICS} entries={entries} onChange={setEntries} />
}

describe('validateTopicMix', () => {
  it('requires the weights to sum to exactly 100', () => {
    expect(validateTopicMix([entry({ weight: 100 })])).toEqual([])
    expect(validateTopicMix([entry({ weight: 60 })])[0].message).toMatch(
      /sum to 100 \(currently 60\)/,
    )
    expect(validateTopicMix([entry({ weight: 120 })])[0].message).toMatch(
      /currently 120/,
    )
  })

  it('accepts several rows that together make 100', () => {
    expect(
      validateTopicMix([
        entry({ topic_id: 't1', weight: 40 }),
        entry({ topic_id: 't2', weight: 60 }),
      ]),
    ).toEqual([])
  })

  it('rejects an empty mix, duplicate topics and inverted difficulty', () => {
    expect(validateTopicMix([])[0].message).toMatch(/at least one topic/i)
    expect(
      validateTopicMix([
        entry({ topic_id: 't1', weight: 50 }),
        entry({ topic_id: 't1', weight: 50 }),
      ]).some((p) => /only appear once/i.test(p.message)),
    ).toBe(true)
    expect(
      validateTopicMix([
        entry({ weight: 100, difficulty_min: 4, difficulty_max: 2 }),
      ]).some((p) => /low to high/i.test(p.message)),
    ).toBe(true)
  })

  it('requires a topic on every row', () => {
    expect(
      validateTopicMix([entry({ topic_id: '', weight: 100 })]).some((p) =>
        /needs a topic/i.test(p.message),
      ),
    ).toBe(true)
  })

  it('sums weights defensively when a field is blank', () => {
    expect(totalWeight([entry({ weight: NaN })])).toBe(0)
  })
})

describe('TopicMixEditor', () => {
  it('shows the running total and flags it until it reaches 100', async () => {
    render(<Harness initial={[entry({ weight: 40 })]} />)

    expect(screen.getByTestId('weight-total')).toHaveTextContent(
      'Total weight: 40 / 100',
    )
    expect(screen.getByRole('alert')).toHaveTextContent(/sum to 100/i)

    const weight = screen.getByLabelText('Weight for row 1')
    await userEvent.clear(weight)
    await userEvent.type(weight, '100')

    expect(screen.getByTestId('weight-total')).toHaveTextContent(
      'Total weight: 100 / 100',
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('adds and removes topic rows', async () => {
    render(<Harness initial={[entry({ weight: 100 })]} />)
    expect(screen.getAllByRole('row')).toHaveLength(2) // header + 1

    await userEvent.click(screen.getByRole('button', { name: /add topic/i }))
    expect(screen.getAllByRole('row')).toHaveLength(3)
    // Two rows of 100 each — now over budget.
    expect(screen.getByTestId('weight-total')).toHaveTextContent('200 / 100')

    await userEvent.click(screen.getAllByRole('button', { name: /remove/i })[1])
    expect(screen.getAllByRole('row')).toHaveLength(2)
    expect(screen.getByTestId('weight-total')).toHaveTextContent('100 / 100')
  })

  it('lets a topic be chosen for a row', async () => {
    render(<Harness initial={[entry({ topic_id: '', weight: 100 })]} />)
    await userEvent.selectOptions(
      screen.getByLabelText('Topic for row 1'),
      'graphs',
    )
    expect(screen.getByLabelText('Topic for row 1')).toHaveValue('t2')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
