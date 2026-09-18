import { useEffect, useState } from 'react'

const TYPE_MS = 55
const DELETE_MS = 25
const HOLD_MS = 1600
const TICK_MS = 5

/**
 * Types the given names into a placeholder one by one (B5): 55 ms per typed character,
 * a 1.6 s hold, 25 ms per deleted character. A plain setInterval; frozen when `active` is
 * false (the field is focused or has text) or when the OS asks for reduced motion.
 */
export function useTypingPlaceholder(names: string[], active: boolean, reducedMotion: boolean) {
  const [text, setText] = useState(() => (reducedMotion || !active ? (names[0] ?? '') : ''))

  useEffect(() => {
    if (reducedMotion || !active || names.length === 0) {
      setText(names[0] ?? '')
      return
    }
    let nameIndex = 0
    let length = 0
    let phase: 'typing' | 'holding' | 'deleting' = 'typing'
    let wait = TYPE_MS
    const timer = setInterval(() => {
      wait -= TICK_MS
      if (wait > 0) return
      const name = names[nameIndex % names.length]
      if (phase === 'typing') {
        length = Math.min(name.length, length + 1)
        setText(name.slice(0, length))
        if (length === name.length) {
          phase = 'holding'
          wait = HOLD_MS
        } else {
          wait = TYPE_MS
        }
      } else if (phase === 'holding') {
        phase = 'deleting'
        wait = DELETE_MS
      } else {
        length = Math.max(0, length - 1)
        setText(name.slice(0, length))
        if (length === 0) {
          phase = 'typing'
          nameIndex += 1
        }
        wait = length === 0 ? TYPE_MS : DELETE_MS
      }
    }, TICK_MS)
    return () => clearInterval(timer)
  }, [names, active, reducedMotion])

  return text
}
