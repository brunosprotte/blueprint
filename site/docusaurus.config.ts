import type { Config } from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'Blueprint SDD',
  tagline: 'Ambiente Spec-Driven de multiagentes',
  url: process.env.SDD_SITE_URL ?? 'http://localhost:8000',
  baseUrl: '/',
  onBrokenLinks: 'throw',
  onBrokenAnchors: 'warn',
  markdown: {
    format: 'detect',
    hooks: { onBrokenMarkdownLinks: 'throw' }
  },
  i18n: {
    defaultLocale: 'pt-BR',
    locales: ['pt-BR']
  },
  presets: [
    [
      'classic',
      {
        docs: {
          path: 'docs',
          routeBasePath: 'docs',
          sidebarPath: './sidebars.ts',
          showLastUpdateTime: false
        },
        blog: false,
        theme: { customCss: './src/css/custom.css' }
      } satisfies Preset.Options
    ]
  ],
  themeConfig: {
    navbar: {
      title: 'Blueprint SDD',
      items: [
        { type: 'docSidebar', sidebarId: 'metodo', position: 'left', label: 'Método' },
        { type: 'docSidebar', sidebarId: 'demandas', position: 'left', label: 'Demandas' }
      ]
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Blueprint',
          items: [
            { label: 'Método', to: '/docs/metodo/' },
            { label: 'Demandas', to: '/docs/demandas/' }
          ]
        }
      ],
      copyright: 'Blueprint — SDD multiagentes'
    }
  }
};

export default config;
