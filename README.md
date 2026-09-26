# 声学应急控制器 · 规程等价复核服务

海底观测站更换声学应急控制器前，需要确认候选规程（Markov 随机过程）对
**任意有限命令串**（含空串）产生的“最终进入安全态”概率都与现网规程
**精确相同**。本服务以任意精度有理数完成这一判定，并在不等价时返回
**按长度最短、同长度按 ASCII 字典序最小**的反例及两侧逐步分布与概率差。

## 它保证什么

- **精确**：所有概率用 Python `fractions.Fraction`（任意精度有理数）解析、
  相乘、消元与比较；全程不使用浮点数。响应里附带的小数仅用于展示，绝不参与判定。
- **覆盖所有有限命令串**：判定基于有理线性空间的基扩展（见“判定原理”），
  **不枚举长度上限内的字符串**，因此结论对任意长度成立且必然终止。
- **最小反例**：对生成的分布对做 BFS（命令按 ASCII 码排序），第一个命中的
  反例既是最短、又是同长度下 ASCII 字典序最小。
- **逐步可追溯**：反例响应包含两侧每一步（含初始的空串步）的完整分布、
  逐步安全概率、最终安全概率及精确概率差 `P_A − P_B`。
- **严格校验**：概率和不为 1、非法分数（含分母为 0、负数）、悬空/缺失安全态、
  矩阵尺寸错误、非 ASCII 或重复命令都会以 HTTP 422 返回**结构化、可定位**
  的错误（精确到侧、区域、命令、行、列）；前端收到错误会清除旧结论并高亮位置。

## 判定原理（不枚举串长）

设两侧状态数为 `n_a, n_b`，命令 `c` 的行随机矩阵为 `M_c^A, M_c^B`。
执行命令串 `w` 后，两侧分布为 `(u_w, v_w)`，把它嵌入到
`x_w = (u_w | v_w) ∈ Q^(n_a+n_b)`。令安全指示向量
`g = (1_S^A | −1_S^B)`，则两侧安全概率相等当且仅当 `x_w · g = 0`。

从空串的 `x_ε` 出发做可达对扩展：

1. 每个新到达的 `x_w` 先检查 `x_w · g`；非零即为反例（BFS + ASCII 序保证最小）。
2. 若 `x_w` 落在已有基的有理张成内，则它与所有命令矩阵的像都可由基元素的
   线性组合生成，剪枝不会丢失任何可达对，也不会丢失反例；
3. 否则把它消元后加入阶梯基。基最多有 `n_a+n_b` 个元素，故算法必然终止；
   基满秩或队列穷尽且每个基向量都与 `g` 正交时，判定**对所有有限命令串等价**。

消元在整数上进行（叉乘 `v := b_p v − v_p b` 后做 gcd 原始化），
避免分母连乘导致的位数膨胀；`n=30、k=10` 的既约分数矩阵可在秒级完成。

> 命令字母表取两侧的并集；若某命令只在一侧定义，则该单字符串在另一侧无
> 对应转移，直接作为反例返回（响应中标注 `note`，对应一侧最终概率为 `null`）。

## 目录结构

```
app/equivalence.py   有理数解析、校验、精确等价判定（核心引擎，无 Web 依赖）
app/main.py          FastAPI：/health、/api/compare、静态页面
static/index.html    录入 / 复核 / 草稿 / 错误定位 / 结论与反例展示的单页前端
tests/test_engine.py      引擎单元测试（等价构造、最短反例、超大分数等）
tests/test_bruteforce.py  与深度枚举暴力交叉验证（400 组随机规程）
tests/test_api.py         经真实 FastAPI 栈的接口测试
tests/verify_all.py       Compose verify 服务的一次性验收脚本
Dockerfile / docker-compose.yml / scripts/verify.sh
```

## 本地运行（不使用 Docker）

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
# 打开 http://localhost:8080
```

## Docker / Compose 发布与配置

构建并启动（健康检查与宿主端口均可通过环境变量配置）：

```bash
cp .env.example .env        # 可选：修改 APP_PORT / HOST_PORT / 健康检查参数
docker compose up -d --build web
docker compose ps           # health=healthy 后访问 http://localhost:${HOST_PORT}
```

| 变量 | 默认 | 含义 |
| --- | --- | --- |
| `APP_PORT` | `8080` | 容器内监听端口（Dockerfile 与 Compose 健康检查均读取） |
| `HOST_PORT` | `8080` | 宿主机映射端口（`HOST_PORT:APP_PORT`） |
| `HEALTH_INTERVAL` / `HEALTH_TIMEOUT` / `HEALTH_START_PERIOD` | `10s/3s/5s` | 健康检查参数 |

健康检查命中容器内 `GET /health`，端口随 `APP_PORT` 变化。

## 一次性验收（verify，退出码即验收结论）

```bash
./scripts/verify.sh
# 或： docker compose build && docker compose run --rm verify
```

`verify` 服务依次：

1. **检查构建**（同一镜像构建 web 与 verify）；
2. 等待 `web` 健康检查通过；
3. 断言**最短概率反例**（长度/ASCII 序、逐步与最终精确概率、`1/10^40` 级精确差）、
   运行全部引擎单元测试、与深度枚举做随机交叉验证；
4. 对**真实 HTTP API** 冒烟：`/health`、等价结论、反例结论（含逐步概率与差）、
   422 错误定位。

全部通过输出 `ACCEPTANCE PASSED` 并以 **退出码 0** 结束；任一失败输出
`ACCEPTANCE FAILED` 并以非零退出码结束，可直接用于 CI 门禁。

## HTTP API

`POST /api/compare`

```json
{
  "a": {"states":["s","t"], "initial":["1","0"], "safe":["s"],
        "commands":["x"],
        "matrices":{"x":[["1/3","2/3"],["1/3","2/3"]]}},
  "b": { "...": "同结构，状态数可不同" }
}
```

- 等价：`200 {"ok":true,"equivalent":true,...}`
- 不等价：`200 {"ok":true,"equivalent":false,"witness":{
  "word","length","wordCodes","steps":[{index,command,distA,distB,safeA,safeB}],
  "statesA","statesB","finalA","finalB","difference", ...}}`
- 输入非法：`422 {"ok":false,"errors":[{"side","area","message",
  "index","command","row","col"}]}`

矩阵约定：`matrices[c][i][j]` 为命令 `c` 下从状态 `i` 转移到状态 `j`
的概率，**每行之和必须恰为 1**；分数支持 `p/q` 与整数。
