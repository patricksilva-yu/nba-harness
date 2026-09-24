import * as Headless from '@headlessui/react'
import { Bars2Icon, XMarkIcon } from '@heroicons/react/20/solid'
import { useEffect, useState } from 'react'
import { NavbarItem } from '../components/navbar'

function useMediaQuery(query) {
  let [matches, setMatches] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    let media = window.matchMedia(query)
    let update = () => setMatches(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [query])
  return matches
}

function Drawer({ open, onClose, side, label, children }) {
  let left = side === 'left'
  return (
    <Headless.Dialog open={open} onClose={onClose}>
      <Headless.DialogBackdrop
        transition
        className="fixed inset-0 z-40 bg-black/30 transition data-closed:opacity-0 data-enter:duration-300 data-enter:ease-out data-leave:duration-200 data-leave:ease-in"
      />
      <Headless.DialogPanel
        transition
        aria-label={label}
        className={
          'fixed inset-y-0 z-50 w-full p-2 transition duration-300 ease-in-out ' +
          (left ? 'left-0 max-w-80 data-closed:-translate-x-full' : 'right-0 max-w-md data-closed:translate-x-full')
        }
      >
        <div className="flex h-full flex-col rounded-lg bg-white shadow-xs ring-1 ring-zinc-950/5 dark:bg-zinc-900 dark:ring-white/10">
          {left && (
            <div className="-mb-3 px-4 pt-3">
              <Headless.CloseButton as={NavbarItem} aria-label="Close navigation">
                <XMarkIcon />
              </Headless.CloseButton>
            </div>
          )}
          {children}
        </div>
      </Headless.DialogPanel>
    </Headless.Dialog>
  )
}

// Catalyst's SidebarLayout, extended with a right-hand panel that docks beside
// the content on wide screens and slides over it on narrower ones.
export function AppShell({ navbar, sidebar, panel, panelOpen, onClosePanel, children }) {
  let [showSidebar, setShowSidebar] = useState(false)
  let wide = useMediaQuery('(min-width: 80rem)')
  let docked = panelOpen && wide

  return (
    <div className="relative isolate flex min-h-svh w-full bg-white max-lg:flex-col lg:bg-zinc-100 dark:bg-zinc-900 dark:lg:bg-zinc-950">
      <div className="fixed inset-y-0 left-0 w-64 max-lg:hidden">{sidebar}</div>

      <Drawer open={showSidebar} onClose={() => setShowSidebar(false)} side="left" label="Navigation">
        {sidebar}
      </Drawer>

      <header className="flex items-center border-b border-zinc-950/5 px-4 lg:hidden dark:border-white/5">
        <div className="py-2.5">
          <NavbarItem onClick={() => setShowSidebar(true)} aria-label="Open navigation">
            <Bars2Icon />
          </NavbarItem>
        </div>
        <div className="min-w-0 flex-1">{navbar}</div>
      </header>

      <main
        className={
          'flex flex-1 flex-col lg:min-w-0 lg:pt-2 lg:pr-2 lg:pb-2 lg:pl-64 ' + (docked ? 'xl:pr-[27rem]' : '')
        }
      >
        <div className="flex grow flex-col lg:rounded-lg lg:bg-white lg:shadow-xs lg:ring-1 lg:ring-zinc-950/5 dark:lg:bg-zinc-900 dark:lg:ring-white/10">
          {children}
        </div>
      </main>

      {docked && (
        <aside
          aria-label="Show your work"
          className="fixed inset-y-2 right-2 flex w-[26.5rem] flex-col rounded-lg bg-white shadow-xs ring-1 ring-zinc-950/5 dark:bg-zinc-900 dark:ring-white/10"
        >
          {panel}
        </aside>
      )}
      {!wide && (
        <Drawer open={panelOpen} onClose={onClosePanel} side="right" label="Show your work">
          {panel}
        </Drawer>
      )}
    </div>
  )
}
