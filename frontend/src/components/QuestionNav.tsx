import type { AssignedQuestion } from '../api/types'

import './QuestionNav.css'

interface QuestionNavProps {
  questions: AssignedQuestion[]
  activeOrdinal: number | null
  onSelect: (ordinal: number) => void
}

export function QuestionNav({
  questions,
  activeOrdinal,
  onSelect,
}: QuestionNavProps) {
  return (
    <nav className="question-nav" aria-label="Assigned questions">
      {questions.map((question) => (
        <button
          key={question.ordinal}
          type="button"
          className={`question-nav__item${
            question.ordinal === activeOrdinal ? ' question-nav__item--active' : ''
          }`}
          aria-current={question.ordinal === activeOrdinal}
          onClick={() => onSelect(question.ordinal)}
        >
          Q{question.ordinal}
        </button>
      ))}
    </nav>
  )
}
