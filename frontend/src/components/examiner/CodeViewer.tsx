import Editor from '@monaco-editor/react'

interface CodeViewerProps {
  language: string
  source: string
  height?: string
}

const MONACO_LANGUAGE: Record<string, string> = {
  python: 'python',
  java: 'java',
  cpp: 'cpp',
}

/** Read-only Monaco for reviewing what a candidate submitted. */
export function CodeViewer({ language, source, height = '360px' }: CodeViewerProps) {
  return (
    <Editor
      height={height}
      theme="vs-dark"
      language={MONACO_LANGUAGE[language] ?? 'plaintext'}
      value={source}
      options={{
        readOnly: true,
        domReadOnly: true,
        minimap: { enabled: false },
        fontSize: 13,
        scrollBeyondLastLine: false,
      }}
    />
  )
}
