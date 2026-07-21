import { useContext } from 'react'

import { ExaminerAuthContext } from './ExaminerAuthContext'

export function useExaminerAuth() {
  const value = useContext(ExaminerAuthContext)
  if (!value) {
    throw new Error('useExaminerAuth must be used inside ExaminerAuthProvider')
  }
  return value
}
