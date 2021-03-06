#include <torch/extension.h>
// #include "pybind.hpp"

// void init_basic(py::module &);
void init_gather(py::module &);
void init_scatter(py::module &);
void init_search(py::module &);
void init_fold(py::module &);
void init_unfold(py::module &);
void init_iunfold(py::module &);
void init_xsearch(py::module &);
void init_wpsum(py::module &);


PYBIND11_MODULE(TORCH_EXTENSION_NAME, m) {
  init_gather(m);
  init_scatter(m);
  init_search(m);
  init_fold(m);
  init_unfold(m);
  init_iunfold(m);
  init_xsearch(m);
  init_wpsum(m);
}


