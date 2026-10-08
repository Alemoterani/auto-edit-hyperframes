# vendor/

Código de terceiros embutido neste repositório.

| Pasta | Projeto | Versão | Commit de origem | Licença |
|---|---|---|---|---|
| `hyperframes/` | [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes) | 0.8.141 | `188475aaf2cc94d05a5a641341cab3020c131f16` (2026-10-08) | Apache 2.0 — ver `hyperframes/LICENSE` |

A cópia é um snapshot sem histórico e sem `packages/producer/tests/` (≈45 MB de
vídeos de regressão em Git LFS). As regras de LFS do `.gitattributes` original
foram removidas; o resto do código está inalterado.

O auto-edit lê a versão em `hyperframes/packages/cli/package.json` e roda
`npx hyperframes@<essa versão>`, então o que renderiza é sempre a mesma versão
deste código.

## Atualizar

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 https://github.com/heygen-com/hyperframes /tmp/hf
rm -rf vendor/hyperframes && mkdir -p vendor/hyperframes
git -C /tmp/hf archive HEAD -- . ':(exclude)packages/producer/tests' | tar -x -C vendor/hyperframes
sed -i '/filter=lfs/d' vendor/hyperframes/.gitattributes
```

Depois atualize a tabela acima (versão e commit) e rode `pytest`.
