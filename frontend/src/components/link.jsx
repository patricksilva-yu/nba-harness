import * as Headless from '@headlessui/react'
import React, { forwardRef } from 'react'
import { handleLinkClick } from '../app/router'

// Catalyst's Link, wired to the app's History API router.
export const Link = forwardRef(function Link({ onClick, ...props }, ref) {
  return (
    <Headless.DataInteractive>
      <a
        {...props}
        ref={ref}
        onClick={(event) => {
          onClick?.(event)
          handleLinkClick(event, props.href, props.target)
        }}
      />
    </Headless.DataInteractive>
  )
})
