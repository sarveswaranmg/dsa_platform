import Editor from '@monaco-editor/react'

import { LANGUAGES, type Language } from '../api/types'

import './CodeEditor.css'

interface CodeEditorProps {
  language: Language
  source: string
  disabled?: boolean
  onLanguageChange: (language: Language) => void
  onSourceChange: (source: string) => void
  onRun: () => void
  onSubmit: () => void
  busy?: boolean
}

const MONACO_LANGUAGE: Record<Language, string> = {
  python: 'python',
  java: 'java',
  cpp: 'cpp',
}

export function CodeEditor({
  language,
  source,
  disabled = false,
  onLanguageChange,
  onSourceChange,
  onRun,
  onSubmit,
  busy = false,
}: CodeEditorProps) {
  return (
    <section className="editor" aria-label="Code editor">
      <div className="editor__toolbar">
        <label className="editor__language">
          <span>Language</span>
          <select
            value={language}
            disabled={disabled}
            onChange={(event) => onLanguageChange(event.target.value as Language)}
          >
            {LANGUAGES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <div className="editor__actions">
          <button
            type="button"
            className="editor__button"
            onClick={onRun}
            disabled={disabled || busy}
          >
            Run sample tests
          </button>
          <button
            type="button"
            className="editor__button editor__button--primary"
            onClick={onSubmit}
            disabled={disabled || busy}
          >
            Submit
          </button>
        </div>
      </div>
      <div className="editor__monaco">
        <Editor
          height="100%"
          theme="vs-dark"
          language={MONACO_LANGUAGE[language]}
          value={source}
          onChange={(value) => onSourceChange(value ?? '')}
          options={{
            readOnly: disabled,
            minimap: { enabled: false },
            fontSize: 13,
            scrollBeyondLastLine: false,
          }}
        />
      </div>
    </section>
  )
}
