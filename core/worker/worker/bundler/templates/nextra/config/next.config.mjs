import nextra from 'nextra'

const withNextra = nextra({
  // ... Add Nextra-specific options here
})

export default withNextra({
  // ... Add regular Next.js options here
  turbopack: {
    resolveAlias: {
      // Path to your `mdx-components` file with extension
      'next-mdx-import-source-file': './mdx-components.js'
    }
  }
})
