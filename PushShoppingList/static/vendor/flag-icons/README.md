# flag-icons artwork

The flag artwork in `flags-4x3.svg` comes from
[`flag-icons` 7.5.0](https://github.com/lipis/flag-icons/tree/v7.5.0), which is
distributed under the MIT license in [LICENSE](./LICENSE).

This bundle contains the 249 `iso: true` entries from the package's
`country.json`. Each upstream 4x3 SVG was wrapped in a uniquely named
`flag-icons-xx` symbol in one local sprite; its inner artwork is unchanged.
Non-ISO convenience entries such as XK, EU, and UN are intentionally omitted.

Cuisine icon tokens use the stable form `flag:xx`. The application renders a
token with an SVG `<use>` reference to `#flag-icons-xx`. This creates one
cacheable, same-origin asset request instead of one request per flag and does
not require a CDN or other runtime network access.

Package integrity recorded when vendored:

`sha512-kd+MNXviFIg5hijH766tt+3x76ele1AXlo4zDdCxIvqWZhKt4T83bOtxUOOMlTx/EcFdUMH5yvQgYlFh1EqqFg==`
