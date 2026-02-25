/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Brand palette
        primary: {
          // Teal
          DEFAULT: '#80CBC4',
          50: '#ECF8F7',
          100: '#D9F1EF',
          200: '#B4EBE6',
          300: '#80CBC4',
          400: '#5FB9B0',
          500: '#3FA59A',
          600: '#2F8179',
          700: '#225F59',
          800: '#153E3A',
          900: '#0B2321',
        },
        // Dedicated peach token for ad-hoc utilities
        peach: '#fcb785',
        accent: {
          // Amber
          DEFAULT: '#fcb785',
          50: '#FFF4DE',
          100: '#FFE9BD',
          200: '#FFD98A',
          300: '#FFCA57',
          400: '#FFB433',
          500: '#E99F1E',
          600: '#C28010',
          700: '#996508',
          800: '#704904',
          900: '#4A3002',
        },
        surface: '#B4EBE6',
        background: '#FBF8EF',
        // Backwards compat alias
        secondary: {
          DEFAULT: '#FFB433',
          dark: '#C28010',
        },
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
    require('@tailwindcss/forms'),
  ],
}
