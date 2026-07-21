import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

// Monaco cannot run under jsdom; tests that render the editor get a plain
// textarea with the same value/onChange contract.
vi.mock('@monaco-editor/react', async () => {
  const React = await import('react')
  return {
    default: ({
      value,
      onChange,
    }: {
      value?: string
      onChange?: (value: string | undefined) => void
    }) =>
      React.createElement('textarea', {
        'data-testid': 'monaco',
        value: value ?? '',
        onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) =>
          onChange?.(e.target.value),
      }),
  }
})
