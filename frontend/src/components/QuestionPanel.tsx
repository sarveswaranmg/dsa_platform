import Markdown from 'react-markdown'

import type { QuestionContent } from '../api/types'

import './QuestionPanel.css'

interface QuestionPanelProps {
  question: QuestionContent
}

export function QuestionPanel({ question }: QuestionPanelProps) {
  return (
    <article className="question" aria-label="Question statement">
      <header className="question__header">
        <h2 className="question__title">{question.title}</h2>
        <p className="question__meta">
          Difficulty {question.difficulty} · {question.time_limit_ms} ms ·{' '}
          {question.memory_limit_mb} MB
        </p>
      </header>
      <div className="question__body">
        <Markdown>{question.statement_md}</Markdown>
        {question.constraints_md && (
          <>
            <h3>Constraints</h3>
            <Markdown>{question.constraints_md}</Markdown>
          </>
        )}
      </div>
    </article>
  )
}
