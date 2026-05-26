module.exports = {
  humarinApi: {
    input: 'http://158.160.194.41:8000/openapi.json',
    output: {
      namingConvention: 'kebab-case',
      mode: 'single',
      target: 'src/entities/generated/endpoints',
      schemas: 'src/entities/generated/model',
      mock: {
        type: 'msw',
        delay: 1000,
        useExamples: false,
      },
      docs: true,
      clean: true,
      prettier: true,
      tslint: true,
      client: 'react-query',
      indexFiles: true,
      override: {
        mutator: {
          path: 'src/shared/lib/axios-custom-instance.ts',
          name: 'customInstance',
        },
      },
    },
  },
  humarinApiZod: {
    input: 'http://158.160.194.41:8000/openapi.json',
    output: {
      namingConvention: 'kebab-case',
      mode: 'single',
      client: 'zod',
      target: 'src/entities/generated/endpoints',
      fileExtension: '.zod.ts',
      indexFiles: true,
    },
  },
}
