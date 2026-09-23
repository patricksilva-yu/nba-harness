import { ArrowUpIcon } from '@heroicons/react/20/solid'
import { useRef, useState } from 'react'
import { Button } from '../components/button'

export function Composer({ placeholder, disabled, onSubmit }) {
  let [value, setValue] = useState('')
  let ref = useRef(null)
  let ready = !disabled && value.trim().length >= 3

  function resize() {
    let el = ref.current
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }

  function submit(event) {
    event.preventDefault()
    if (!ready) return
    onSubmit(value.trim())
    setValue('')
    requestAnimationFrame(resize)
  }

  return (
    <div className="sticky bottom-0 z-10 bg-linear-to-b from-transparent via-white via-30% to-white px-4 pt-5 pb-[max(1rem,env(safe-area-inset-bottom))] sm:px-6 lg:rounded-b-lg dark:via-zinc-900 dark:to-zinc-900">
      <form
        onSubmit={submit}
        className="mx-auto flex max-w-3xl items-end gap-2 rounded-xl bg-white p-2 pl-3.5 shadow-sm ring-1 ring-zinc-950/15 focus-within:ring-2 focus-within:ring-zinc-950/60 dark:bg-zinc-800 dark:ring-white/15 dark:focus-within:ring-white/50"
      >
        <label htmlFor="question" className="sr-only">
          Ask a question about this game
        </label>
        <textarea
          id="question"
          ref={ref}
          rows={1}
          value={value}
          placeholder={placeholder}
          onChange={(e) => {
            setValue(e.target.value)
            resize()
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) submit(e)
          }}
          className="max-h-40 min-h-6 flex-1 resize-none bg-transparent py-1.5 text-base/6 text-zinc-950 placeholder:text-zinc-500 focus:outline-none sm:text-[15px]/6 dark:text-white dark:placeholder:text-zinc-400"
        />
        <Button type="submit" color="dark/zinc" disabled={!ready} aria-label="Ask" className="size-9 px-0! py-0!">
          <ArrowUpIcon />
        </Button>
      </form>
      <p className="mx-auto mt-1.5 flex max-w-3xl flex-wrap justify-between gap-x-3 text-xs text-zinc-500 dark:text-zinc-400">
        <span>Every claim is fact-checked against the game data before you see it.</span>
        <span className="max-sm:hidden">Enter to ask · Shift+Enter for a new line</span>
      </p>
    </div>
  )
}
