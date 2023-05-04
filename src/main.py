import warnings

import click
import matplotlib.pyplot as plt
import numpy as np
import spacy
import torch
import torch.nn as nn

from sklearn.metrics import ConfusionMatrixDisplay, classification_report
from sklearn.model_selection import cross_validate
from skorch import NeuralNetClassifier
from skorch.callbacks import GradientNormClipping
from torchtext.vocab import GloVe, pretrained_aliases

import deps
from dataset import CollateSemEval, SemEvalDataset
from model import GCNClassifier


# ignore sklearn warnings when members of the least populated class < n_splits
warnings.filterwarnings(action='ignore', category=UserWarning)


def get_parser(model_name="en_core_web_sm"):
    """Loads a dependency parser from spaCy."""
    nlp = spacy.load(model_name)

    # add custom tokenizer and sentence segmentation based on dataset format
    nlp.tokenizer = deps.WhitespaceTokenizer(nlp.vocab)
    nlp.add_pipe("simple_sentencizer", before="parser")

    # disable everything not needed for parsing
    nlp.disable_pipes(['tagger', 'attribute_ruler', 'lemmatizer', 'ner'])

    return nlp


def run_model(net: NeuralNetClassifier, data: SemEvalDataset, num_folds: int):
    """Fits a model on the training data using k-fold cross-validation and
    returns the best estimator."""
    print(f"Running {num_folds}-fold cross-validation")
    print("==================================")

    labels = np.array(data.labels)
    scores = cross_validate(net, data, y=labels, cv=num_folds, return_estimator=True)

    test_scores = scores['test_score']
    print(f"Average accuracy on dev set: {np.mean(test_scores)}")
    best_fold = np.argmax(test_scores)

    return scores['estimator'][best_fold]


def predict(net: NeuralNetClassifier, data: SemEvalDataset):
    """Evaluates a trained model on a test set and displays the predictions in
    a confusion matrix."""
    print("Predicting on test set")
    print("==================================")
    preds = net.predict(data)
    golds = np.array(data.labels)
    return preds, golds


def display_results(preds: np.ndarray, golds: np.ndarray):
    """Prints the classification metrics and displays the confusion matrix
    comparing the predictions and gold labels."""
    print(classification_report(golds, preds, digits=4, zero_division=0))
    ConfusionMatrixDisplay.from_predictions(golds, preds)
    plt.show()


@click.command()
@click.option('--epochs', type=int, default=10,
              help="Number of training epochs")
@click.option('--dr', type=float, default=0.5, help="Dropout value")
@click.option('--lr', type=float, default=5e-4, help="Learning rate")
@click.option('--batch-size', type=int, default=64, help="Batch size")
@click.option('--clip', type=int, default=10, help="Gradient clip value")
@click.option('--patience', type=int, default=5,
              help="Number of epochs to wait before early stopping")
@click.option('--embed-dim', type=click.Choice(['50', '100', '200', '300']),
              default='50', help="Dimensionality of embeddings")
@click.option('--use-pretrained', is_flag=True,
              help="Use pretrained word embeddings")
@click.option('--use-lstm', is_flag=True, help="Use LSTM encoder")
@click.option('--bidirectional', is_flag=True, help="Use BiLSTM")
@click.option('--tune', is_flag=True,
              help="Perform a grid search over all models and hyperparameters")
@click.option('--num-folds', type=int, default=10,
              help="Number of folds to use for K-fold cross-validation")
@click.option('--device', type=click.Choice(['cpu', 'cuda', 'mps']),
              default='cpu', help="Device to run on")
def main(**kwargs):
    nlp = get_parser()

    print("Loading train data...")
    train_data = SemEvalDataset(nlp)
    vocab = train_data.vocab
    num_classes = train_data.num_classes

    print("Loading test data...")
    test_data = SemEvalDataset(nlp, split="test", vocab=vocab)

    embed_dim = int(kwargs["embed_dim"])
    if kwargs["use_pretrained"]:
        embedding_source = f"glove.6B.{embed_dim}d"
        print(f"Loading embeddings from {embedding_source}...")
        pretrained: GloVe = pretrained_aliases[embedding_source]()
        print("Loaded")
    else:
        pretrained = None

    num_folds = kwargs["num_folds"]
    collate_fn = CollateSemEval()

    net = NeuralNetClassifier(
        GCNClassifier,
        module__emb_input_dim=len(vocab),
        module__emb_output_dim=embed_dim,
        module__num_classes=num_classes,
        module__dr=kwargs["dr"],
        module__use_lstm=kwargs["use_lstm"],
        module__pretrained=pretrained,
        module__vocab=vocab,
        iterator_train__collate_fn=collate_fn,
        iterator_valid__collate_fn=collate_fn,
        train_split=None,
        criterion=nn.CrossEntropyLoss,
        optimizer=torch.optim.AdamW,
        batch_size=kwargs["batch_size"],
        lr=kwargs["lr"],
        max_epochs=kwargs["epochs"],
        callbacks=[GradientNormClipping(gradient_clip_value=kwargs["clip"])],
        device=kwargs["device"]
    )

    net = run_model(net, train_data, num_folds)
    preds, golds = predict(net, test_data)
    print()
    display_results(preds, golds)


if __name__ == "__main__":
    main()
