const KEY = 'dsa.exam_token'

/** The exam-scoped candidate JWT. sessionStorage (not localStorage) so it
 *  dies with the tab — it is only valid inside the exam window anyway. */
export function getExamToken(): string | null {
  return sessionStorage.getItem(KEY)
}

export function setExamToken(token: string): void {
  sessionStorage.setItem(KEY, token)
}

export function clearExamToken(): void {
  sessionStorage.removeItem(KEY)
}
